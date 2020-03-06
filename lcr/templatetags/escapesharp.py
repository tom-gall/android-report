## https://docs.djangoproject.com/en/2.0/howto/custom-template-tags/
from django import template

register = template.Library()

@register.filter('escapesharp')
def escapesharp(text):
    return str(text).replace('#', '%23')
