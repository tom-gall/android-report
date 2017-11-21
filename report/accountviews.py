# -*- coding: utf-8 -*-
# http://gswd-a-crash-course-pycon-2014.readthedocs.io/en/latest/authviews.html
# https://simpleisbetterthancomplex.com/tutorial/2017/02/18/how-to-create-user-sign-up-view.html
# https://docs.djangoproject.com/en/1.11/topics/auth/default/
from __future__ import unicode_literals
from __future__ import absolute_import

from django.views import generic
from django.utils.http import is_safe_url

from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout, REDIRECT_FIELD_NAME
from django.core.urlresolvers import reverse_lazy

from .forms import RegistrationForm
from .forms import LoginForm

class SignUpView(generic.CreateView):
    form_class = RegistrationForm
    model = User
    template_name = 'accounts/signup.html'
    success_url = reverse_lazy('home')


class LoginView(generic.FormView):
    form_class = LoginForm
    success_url = reverse_lazy('home')
    template_name = 'accounts/login.html'
    redirect_field_name = REDIRECT_FIELD_NAME

    def form_valid(self, form):
        username = form.cleaned_data['username']
        password = form.cleaned_data['password']
        user = authenticate(username=username, password=password)

        if user is not None and user.is_active:
            login(self.request, user)
            return super(LoginView, self).form_valid(form)
        else:
            return self.form_invalid(form)


    def get_success_url(self):
        redirect_to = self.request.GET.get(self.redirect_field_name)
        if not is_safe_url(url=redirect_to, host=self.request.get_host()):
            redirect_to = self.success_url
        return redirect_to


class LogOutView(generic.RedirectView):
    url = reverse_lazy('home')

    def get(self, request, *args, **kwargs):
        logout(request)
        return super(LogOutView, self).get(request, *args, **kwargs)
