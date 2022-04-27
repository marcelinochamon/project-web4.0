from django import forms

from .models import Friend

# class FriendForm(forms.ModelForm):
#     name = forms.CharField(widget =forms.TextInput())
#     message = forms.CharField(
#                         required=False,
#                         widget=forms.Textarea(
#                             attrs={
#                                 "class":"new-class-name two",
#                                 "rows": 20,
#                                 "cols": 120
#                                 }
#                             )
#                         )
#     email = forms.EmailField(required=True)
#     school = forms.CharField()
#     SCHOOL_CHOICES = [('UT','UT -- I LOVE UT'), ('OU','OU (I got rejected from UT)'), ('Texas A&M','Texas ATM (I also got rejected from UT but am less relevant)')]
#     best_school = forms.ChoiceField(required=False, widget=forms.RadioSelect, choices=SCHOOL_CHOICES)


#     class Meta:
#         model = Friend

#         fields = [
#             'name',
#             'message',
#             'email',
#             'school',
#             'best_school',
#         ]
