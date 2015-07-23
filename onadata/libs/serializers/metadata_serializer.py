from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.translation import ugettext as _
from rest_framework import serializers

from onadata.apps.main.models.meta_data import MetaData

CSV_CONTENT_TYPE = 'text/csv'
MEDIA_TYPE = 'media'
METADATA_TYPES = (
    ('data_license', _(u"Data License")),
    ('form_license', _(u"Form License")),
    ('mapbox_layer', _(u"Mapbox Layer")),
    (MEDIA_TYPE, _(u"Media")),
    ('public_link', _(u"Public Link")),
    ('source', _(u"Source")),
    ('supporting_doc', _(u"Supporting Document")),
    ('external_export', _(u"External Export")),
    ('textit', _(u"External Export"))
)


class MetaDataSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.IntegerField(source='pk', read_only=True)
    xform = serializers.PrimaryKeyRelatedField()
    data_value = serializers.CharField(max_length=255,
                                       required=True)
    data_type = serializers.ChoiceField(choices=METADATA_TYPES)
    data_file = serializers.FileField(required=False)
    data_file_type = serializers.CharField(max_length=255, required=False)
    media_url = serializers.SerializerMethodField()
    date_created = serializers.IntegerField(source='date_created',
                                            read_only=True)

    class Meta:
        model = MetaData
        fields = ('id', 'xform', 'data_value', 'data_type', 'data_file',
                  'data_file_type', 'media_url', 'file_hash', 'url',
                  'date_created')

    def get_media_url(self, obj):
        if obj.data_type == MEDIA_TYPE and getattr(obj, "data_file") \
                and getattr(obj.data_file, "url"):
            return obj.data_file.url

        return None

    def validate(self, attrs):
        """Ensure we have a valid url if we are adding a media uri
        instead of a media file
        """
        value = attrs.get('data_value')
        media = attrs.get('data_type')
        data_file = attrs.get('data_file')

        if media == 'media' and data_file is None:
            try:
                URLValidator()(value)
            except ValidationError:
                raise serializers.ValidationError(_(
                    u"Invalid url %s." % value
                ))

        return attrs

    def create(self, validated_data):
        data_type = validated_data.get('data_type')
        data_file = validated_data.get('data_file')
        xform = validated_data.get('xform')
        data_value = data_file.name \
            if data_file else validated_data.get('data_value')
        data_file_type = data_file.content_type if data_file else None

        # not exactly sure what changed in the requests.FILES for django 1.7
        # csv files uploaded in windows do not have the text/csv content_type
        # this works around that
        if data_type == MEDIA_TYPE and data_file \
                and data_file.name.lower().endswith('.csv') \
                and data_file_type != CSV_CONTENT_TYPE:
            data_file_type = CSV_CONTENT_TYPE

        return MetaData.objects.create(
            data_type=data_type,
            xform=xform,
            data_value=data_value,
            data_file=data_file,
            data_file_type=data_file_type
        )
