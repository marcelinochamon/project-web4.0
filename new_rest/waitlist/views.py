from django.shortcuts import render
# from .forms import FriendForm

def waitlist_view(request):
    # form = FriendForm(request.POST or None)
    # if form.is_valid():
    #     form.save()
    #     form = FriendForm()
    context = {
    #     'form': form
    }
    return render(request, "waitlist.html", context)