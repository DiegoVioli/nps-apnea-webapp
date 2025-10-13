from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

class SocioRegistrationForm(UserCreationForm):
    codice_fiscale = forms.CharField(max_length=16)
    data_nascita = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    
    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields + ('first_name', 'last_name', 'email', 'codice_fiscale', 'data_nascita')