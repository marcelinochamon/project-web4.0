from django import forms

from .models import Wait, Table, Config

class WaitForm(forms.ModelForm):
    name = forms.CharField(max_length=20)
    party_size = forms.IntegerField()

    class Meta:
        model = Wait

        fields = [
            'name',
            'party_size',
        ]

        
class ConfigForm(forms.ModelForm):
    server_names = forms.CharField(max_length = 100, widget=forms.TextInput(attrs={'placeholder': 'Matthew M, John B G'}))
    tables_for_2 = forms.IntegerField()
    tables_for_4 = forms.IntegerField()
    tables_for_6 = forms.IntegerField()
    tables_for_8 = forms.IntegerField()

    class Meta:
        model = Config

        fields = [
            'server_names',
            'tables_for_2',
            'tables_for_4',
            'tables_for_6',
            'tables_for_8'
        ]
