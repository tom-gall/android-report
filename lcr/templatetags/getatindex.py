## https://docs.djangoproject.com/en/2.0/howto/custom-template-tags/
from django import template

register = template.Library()

@register.filter
def get_at_index(list, index):
    return list[index]
