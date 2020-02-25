## https://docs.djangoproject.com/en/2.0/howto/custom-template-tags/
from django import template

register = template.Library()

@register.filter('startswith')
def startswith(text, starts):
    if isinstance(text, str):
        return text.startswith(starts)
    return False
