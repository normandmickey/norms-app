from .labels import get_navigation_resources


def app_labels(_request):
    return {
        'app_navigation_resources': get_navigation_resources(),
    }
