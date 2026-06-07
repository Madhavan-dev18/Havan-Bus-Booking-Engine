# ticketreservation/services.py
from django.db import transaction
from rest_framework.exceptions import ValidationError
from .models import Bus, Booking
from .tasks import generate_and_send_ticket

def process_ticket_transaction(user, bus_id, passengers):
    """
    Handles the atomic transaction for booking seats.
    Keeps the database lock as brief as physically possible.
    """
    requested_seats = [p['seat'] for p in passengers]
    seats_count = len(requested_seats)

    # 1. Database Lock Initialization
    with transaction.atomic():
        # Lock the specific bus row to prevent concurrent overselling
        bus = Bus.objects.select_for_update().get(id=bus_id)

        # 2. Collision Detection
        active_bookings = Booking.objects.filter(bus=bus, status='CONFIRMED')
        already_taken_seats = set()
        for b in active_bookings:
            if b.selected_seats:
                already_taken_seats.update(b.selected_seats)

        overlapping_claims = set(requested_seats).intersection(already_taken_seats)
        if overlapping_claims:
            raise ValidationError({
                "error": f"Transaction dropped. Seats recently booked: {list(overlapping_claims)}"
            })

        if bus.available_seats < seats_count:
            raise ValidationError({
                "error": f"Insufficient capacity. Only {bus.available_seats} remaining."
            })

        # 3. Inventory Mutation
        total_price = bus.price * seats_count
        bus.available_seats -= seats_count
        bus.save()

        # 4. Record Creation
        booking = Booking.objects.create(
            user=user,
            bus=bus,
            selected_seats=requested_seats,
            passenger_details=passengers,
            seats_booked=seats_count,
            total_price=total_price,
            status='CONFIRMED'
        )

    # 5. Background Processing (CRITICAL: Moved OUTSIDE the lock)
    generate_and_send_ticket.delay(booking.id)
    
    return booking