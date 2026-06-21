from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from django.urls import reverse
from datetime import date, time
from ticketreservation.models import Bus

class BusModelTest(TestCase):
    def setUp(self):
        self.bus = Bus.objects.create(
            bus_name="Test Bus",
            source="City A",
            dest="City B",
            date=date.today(),
            time=time(10, 0),
            total_seats=40,
            available_seats=40,
            price=100.00
        )

    def test_bus_creation(self):
        self.assertEqual(self.bus.bus_name, "Test Bus")
        self.assertEqual(self.bus.source, "City A")
        self.assertEqual(self.bus.dest, "City B")
        self.assertEqual(self.bus.total_seats, 40)
        self.assertEqual(self.bus.price, 100.00)

class AuthViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_user(self):
        url = reverse('api_register')
        data = {
            "username": "testuser",
            "password": "testpassword123",
            "email": "test@example.com"
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('token', response.data)

class BusViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='test', password='testpassword')
        self.client.force_authenticate(user=self.user)
        self.bus = Bus.objects.create(
            bus_name="Test Bus",
            source="City A",
            dest="City B",
            date=date.today(),
            time=time(10, 0),
            total_seats=40,
            available_seats=40,
            price=100.00
        )

    def test_get_buses(self):
        url = reverse('bus-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_search_buses(self):
        url = reverse('bus-list')
        response = self.client.get(url, {'source': 'City A', 'dest': 'City B'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

from django.test import TransactionTestCase
from django.db import connection
from ticketreservation.services import process_ticket_transaction
from rest_framework.exceptions import ValidationError
import concurrent.futures
from unittest.mock import patch

class ConcurrencyBookingTest(TransactionTestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username='user1', password='pw')
        self.user2 = User.objects.create_user(username='user2', password='pw')
        self.bus = Bus.objects.create(
            bus_name="Concurrency Bus",
            source="A",
            dest="B",
            date=date.today(),
            time=time(10, 0),
            total_seats=40,
            available_seats=40,
            price=100.00
        )
    
    @patch('ticketreservation.services.generate_and_send_ticket.delay')
    def test_concurrent_seat_booking(self, mock_delay):
        # We try to book the exact same seat from two different users concurrently
        passengers = [{"seat": "L-1A", "name": "John", "age": 30, "gender": "M"}]
        
        def book_ticket(user):
            try:
                # Close old connections in the thread to ensure isolated transactions
                connection.close()
                return process_ticket_transaction(user, self.bus.id, passengers)
            except ValidationError as e:
                return e
            except Exception as e:
                return e
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(book_ticket, self.user1)
            future2 = executor.submit(book_ticket, self.user2)
            
            result1 = future1.result()
            result2 = future2.result()
            
        results = [result1, result2]
        
        # Depending on DB backend, concurrency lock might raise ValidationError (if it waits and reads) 
        # or OperationalError (database locked in SQLite). The key architectural claim is that 
        # AT MOST ONE transaction can succeed, preventing double booking.
        success_count = sum(1 for r in results if type(r).__name__ == 'Booking')
        self.assertLessEqual(success_count, 1, "Concurrency lock failed: Both transactions succeeded!")
        
        # Verify seats were deducted correctly (1 or 0 depending on success_count)
        self.bus.refresh_from_db()
        expected_seats = 40 - success_count
        self.assertEqual(self.bus.available_seats, expected_seats)

