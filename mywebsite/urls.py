from django.contrib import admin
from django.urls import path, include
from django.conf import settings  # Add this import
from django.conf.urls.static import static  # Add this import

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('main.urls')),  # This connects your main app to the root URL
]   

# THIS IS THE CRUCIAL PART - serves media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) 