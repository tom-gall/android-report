## https://docs.djangoproject.com/en/2.0/howto/custom-template-tags/
from django import template

register = template.Library()

@register.filter('escapesharp')
def escapesharp(text):
    if isinstance(text, str):
        return text.replace('#', '%23')
    return None
