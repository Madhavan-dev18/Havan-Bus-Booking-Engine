from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.authtoken.views import obtain_auth_token

# Notice we explicitly imported trigger_daily_buses right here
from .views import BusViewSet, BookingViewSet, RegisterView, trigger_daily_buses 

router = DefaultRouter()
router.register(r'buses', BusViewSet, basename='bus')
router.register(r'bookings', BookingViewSet, basename='booking')

urlpatterns = [
    # Router paths (buses, bookings)
    path('api/', include(router.urls)),
    
    # Authentication paths
    path('api/login/', obtain_auth_token, name='api_token_auth'),
    path('api/register/', RegisterView.as_view(), name='api_register'),
    
    # Internal Automation
    # Notice we added 'api/' to the path and removed 'views.'
    path('api/internal/generate-buses/', trigger_daily_buses, name='trigger_buses'), 
]