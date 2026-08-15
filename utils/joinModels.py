import json

from django.core import serializers


class JoinModels:
    def __int__(self, model1, model2):
        json_model1 = serializers.serialize("json", model1)
        json_model2 = serializers.serialize("json", model2)

        fields_model1 = json.loads(json_model1)[0]['fields']
        fields_model2 = json.loads(json_model2)[0]['fields']

        fields_model1.pop('password', None)

        return fields_model1 | fields_model2
