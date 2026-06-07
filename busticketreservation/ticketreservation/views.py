# ticketreservation/views.py
import os
import hmac
from django.conf import settings
from django.http import FileResponse, JsonResponse
from django.contrib.auth.models import User
from django.core.management import call_command

from rest_framework import viewsets, status, generics, permissions
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import ValidationError

from .models import Bus, Booking
from .serializers import BusSerializer, BookingSerializer, CreateBookingSerializer, RegisterSerializer
from .services import process_ticket_transaction


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            "user": {"username": user.username, "email": user.email},
            "token": token.key
        }, status=status.HTTP_201_CREATED)


class BusViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Bus.objects.all()
    serializer_class = BusSerializer

    def get_queryset(self):
        queryset = Bus.objects.all()
        source = self.request.query_params.get('source')
        dest = self.request.query_params.get('dest')
        date = self.request.query_params.get('date')

        if source: queryset = queryset.filter(source__icontains=source)
        if dest: queryset = queryset.filter(dest__icontains=dest)
        if date: queryset = queryset.filter(date=date)
        return queryset

    @action(detail=True, methods=['get'], url_path='occupied-seats')
    def occupied_seats(self, request, pk=None):
        bus = self.get_object()
        confirmed_bookings = Booking.objects.filter(bus=bus, status='CONFIRMED')
        occupied = [seat for b in confirmed_bookings if b.selected_seats for seat in b.selected_seats]
        return Response({"occupied_seats": occupied}, status=status.HTTP_200_OK)


class BookingViewSet(viewsets.ModelViewSet):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Booking.objects.filter(user=self.request.user).order_by('-booked_on')

    def create(self, request, *args, **kwargs):
        """Skinny view. Delegates business logic to the service layer."""
        input_serializer = CreateBookingSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        try:
            booking = process_ticket_transaction(
                user=request.user,
                bus_id=input_serializer.validated_data['bus_id'],
                passengers=input_serializer.validated_data['passenger_details']
            )
            output_serializer = self.get_serializer(booking)
            return Response(output_serializer.data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'], url_path='download')
    def download_ticket(self, request, pk=None):
        booking = self.get_object() 
        pdf_filename = f"Ticket_{booking.ticket_id}.pdf"
        pdf_path = os.path.join(settings.BASE_DIR, 'generated_tickets', pdf_filename)
        
        if not os.path.exists(pdf_path):
            return Response(
                {"error": "Ticket layout rendering. Wait 5 seconds and retry."},
                status=status.HTTP_404_NOT_FOUND
            )
            
        response = FileResponse(open(pdf_path, 'rb'), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{pdf_filename}"'
        return response


@api_view(['POST'])
@permission_classes([AllowAny]) 
def trigger_daily_buses(request):
    """Secured webhook for GitHub Actions CRON."""
    provided_secret = request.headers.get('Authorization', '')
    expected_secret = f"Bearer {os.environ.get('CRON_SECRET', 'UNSET')}"
    
    # Cryptographically secure string comparison prevents timing attacks
    if not os.environ.get('CRON_SECRET') or not hmac.compare_digest(provided_secret, expected_secret):
        return JsonResponse({"error": "Unauthorized."}, status=401)
        
    try:
        call_command('create_daily_buses')
        return JsonResponse({"message": "Bus generation successful."}, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)