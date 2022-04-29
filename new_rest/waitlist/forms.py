from django import forms

from .models import Wait

class WaitForm(forms.ModelForm):
    name = forms.CharField(max_length=20)
    party_size = forms.IntegerField()

    class Meta:
        model = Wait

        fields = [
            'name',
            'party_size',
        ]
