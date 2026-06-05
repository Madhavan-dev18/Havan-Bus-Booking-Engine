# ticketreservation/views.py
import os
from django.conf import settings
from django.http import FileResponse, JsonResponse
from django.db import transaction
from django.contrib.auth.models import User
from django.core.management import call_command

from rest_framework import viewsets, status, generics, permissions
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.authtoken.models import Token

from .models import Bus, Booking
from .serializers import BusSerializer, BookingSerializer, CreateBookingSerializer, RegisterSerializer
from .tasks import generate_and_send_ticket


class RegisterView(generics.CreateAPIView):
    """Handles new user registration and instantly generates an auth token."""
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        # Instantly generate an auth token for the new user
        token, created = Token.objects.get_or_create(user=user)
        
        return Response({
            "user": {"username": user.username, "email": user.email},
            "token": token.key
        }, status=status.HTTP_201_CREATED)


class BusViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint that allows buses to be viewed and searched."""
    queryset = Bus.objects.all()
    serializer_class = BusSerializer

    def get_queryset(self):
        """Allows dynamic filtering by source, dest, and date via React query parameters."""
        queryset = Bus.objects.all()
        source = self.request.query_params.get('source')
        dest = self.request.query_params.get('dest')
        date = self.request.query_params.get('date')

        if source:
            queryset = queryset.filter(source__icontains=source)
        if dest:
            queryset = queryset.filter(dest__icontains=dest)
        if date:
            queryset = queryset.filter(date=date)
        return queryset

    @action(detail=True, methods=['get'], url_path='occupied-seats')
    def occupied_seats(self, request, pk=None):
        """Returns an array of all unavailable seat labels for this route block."""
        bus = self.get_object()
        confirmed_bookings = Booking.objects.filter(bus=bus, status='CONFIRMED')
        
        occupied = []
        for booking in confirmed_bookings:
            if booking.selected_seats:
                occupied.extend(booking.selected_seats)
            
        return Response({"occupied_seats": occupied}, status=status.HTTP_200_OK)


class BookingViewSet(viewsets.ModelViewSet):
    """API endpoint for creating and viewing multi-seat bookings."""
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Enforces multi-tenant security: Users only see their own rows
        return Booking.objects.filter(user=self.request.user).order_by('-booked_on')

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        input_serializer = CreateBookingSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        bus_id = input_serializer.validated_data['bus_id']
        passengers = input_serializer.validated_data['passenger_details']
        
        # Extract the specific string coordinates from the JSON manifest
        requested_seats = [p['seat'] for p in passengers]
        seats_count = len(requested_seats)

        # Database-level concurrency lock to prevent overselling
        bus = Bus.objects.select_for_update().get(id=bus_id)

        # Fetch all locked seats for this specific bus route
        active_bookings = Booking.objects.filter(bus=bus, status='CONFIRMED')
        already_taken_seats = set()
        for b in active_bookings:
            if b.selected_seats:
                already_taken_seats.update(b.selected_seats)

        # Collision Check Execution
        overlapping_claims = set(requested_seats).intersection(already_taken_seats)
        if overlapping_claims:
            return Response(
                {"error": f"Transaction dropped. The following seats were just booked by another client: {list(overlapping_claims)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if bus.available_seats < seats_count:
            return Response(
                {"error": f"Insufficient capacity. Only {bus.available_seats} seats remaining on this route."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Mutate the bus inventory and lock the transaction
        total_price = bus.price * seats_count
        bus.available_seats -= seats_count
        bus.save()

        booking = Booking.objects.create(
            user=request.user,
            bus=bus,
            selected_seats=requested_seats,
            passenger_details=passengers,
            seats_booked=seats_count,
            total_price=total_price,
            status='CONFIRMED'
        )

        # Trigger background PDF compilation via Celery
        generate_and_send_ticket.delay(booking.id)

        output_serializer = self.get_serializer(booking)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='download')
    def download_ticket(self, request, pk=None):
        """Secured binary file-streaming channel for accessing compiled ticket PDFs."""
        booking = self.get_object() 
        tickets_dir = os.path.join(settings.BASE_DIR, 'generated_tickets')
        pdf_filename = f"Ticket_{booking.ticket_id}.pdf"
        pdf_path = os.path.join(tickets_dir, pdf_filename)
        
        # Guard clause against race-conditions if Celery worker is still rendering
        if not os.path.exists(pdf_path):
            return Response(
                {"error": "Your ticket layout is still rendering in our pipeline. Please wait 5 seconds and try again."},
                status=status.HTTP_404_NOT_FOUND
            )
            
        # Initialize an optimized, chunked filesystem stream read
        response = FileResponse(open(pdf_path, 'rb'), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{pdf_filename}"'
        return response


@api_view(['POST'])
@permission_classes([AllowAny]) 
def trigger_daily_buses(request):
    """Internal endpoint triggered by GitHub Actions to generate buses."""
    provided_secret = request.headers.get('Authorization')
    expected_secret = f"Bearer {os.environ.get('CRON_SECRET')}"
    
    # Security: Reject if the secret is missing or doesn't match
    if not os.environ.get('CRON_SECRET') or provided_secret != expected_secret:
        return JsonResponse({"error": "Unauthorized. Invalid or missing token."}, status=401)
        
    try:
        # Programmatically run the terminal command you built earlier
        call_command('create_daily_buses')
        return JsonResponse({"message": "Bus generation script executed successfully."}, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)