from django.shortcuts import render

# Home page
def home_view(request, *args, **kwargs):
    print(request.user)
    return render(request, "home.html", {})