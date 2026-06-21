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
