from django import forms

from .models import Table

class TableForm(forms.ModelForm):
    TABLE_NUMS = [(1,1),(2,2),(3,3)]
    number = forms.ChoiceField(required=True, widget=forms.RadioSelect, choices=TABLE_NUMS)
    guest = forms.CharField()
    time_seated = forms.TimeField()

    class Meta:
        model = Table

        fields = [
            'number',
            'guest',
            'seats',
            'time_seated',
        ]