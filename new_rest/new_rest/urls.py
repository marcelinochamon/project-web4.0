"""new_rest URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from pages.views import home_view
from waitlist.views import waitlist_view
from waitlist.views import tables_view
from waitlist.views import config_view


urlpatterns = [
    path('', home_view, name = "home"),
    path('admin/', admin.site.urls),
    path('waitlist/', waitlist_view, name = "waitlist"),
    path('tables/', tables_view, name = "tables"),
    path('config/', config_view, name = "config"),
]
