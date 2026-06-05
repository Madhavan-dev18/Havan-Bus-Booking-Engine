from django.core.management.base import BaseCommand
from ticketreservation.models import Bus
from datetime import date, timedelta
import random
from decimal import Decimal

class Command(BaseCommand):
    help = 'Automatically generates 10 buses for tomorrow'

    def handle(self, *args, **kwargs):
        # We schedule buses for tomorrow so users have at least 24 hours to book
        target_date = date.today() + timedelta(days=1)
        
        # Prevent the script from duplicating buses if it accidentally runs twice
        if Bus.objects.filter(date=target_date).exists():
            self.stdout.write(self.style.WARNING(f"Buses for {target_date} already exist. Aborting."))
            return

        cities = ["Chennai", "Bangalore", "Hyderabad", "Coimbatore", "Madurai", "Kochi"]
        bus_types = ["Volvo A/C Semi-Sleeper", "Scania Multi-Axle", "Non A/C Seater", "A/C Sleeper"]
        
        buses_to_create = []

        for i in range(10):
            source = random.choice(cities)
            dest = random.choice([c for c in cities if c != source]) # Prevent Source == Dest
            
            buses_to_create.append(
                Bus(
                    bus_name=f"Havan Express {random.choice(bus_types)}",
                    source=source,
                    dest=dest,
                    date=target_date,
                    time=f"{random.randint(6, 22):02d}:00:00", # Random hour between 6 AM and 10 PM
                    total_seats=40,
                    available_seats=40,
                    price=Decimal(random.randint(600, 1500))
                )
            )

        # bulk_create is infinitely faster than calling .save() 10 times
        Bus.objects.bulk_create(buses_to_create)
        self.stdout.write(self.style.SUCCESS(f"Successfully generated 10 buses for {target_date}."))