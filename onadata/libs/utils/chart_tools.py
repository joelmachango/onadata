import re

from django.db.utils import DataError
from django.http import Http404

from onadata.libs.data.query import get_form_submissions_grouped_by_field
from onadata.libs.utils import common_tags

from onadata.apps.logger.models.xform import XForm
from onadata.apps.logger.models.data_view import DataView
from rest_framework.exceptions import ParseError


# list of fields we can chart
CHART_FIELDS = ['select one', 'integer', 'decimal', 'date', 'datetime',
                'start', 'end', 'today']
# numeric, categorized
DATA_TYPE_MAP = {
    'integer': 'numeric',
    'decimal': 'numeric',
    'datetime': 'time_based',
    'date': 'time_based',
    'start': 'time_based',
    'end': 'time_based',
    'today': 'time_based',
    'calculate': 'numeric',
}

CHARTS_PER_PAGE = 20

POSTGRES_ALIAS_LENGTH = 63


timezone_re = re.compile(r'(.+)\+(\d+)')


def utc_time_string_for_javascript(date_string):
    """
    Convert 2014-01-16T12:07:23.322+03 to 2014-01-16T12:07:23.322+03:00

    Cant use datetime.str[fp]time here since python 2.7's %z is platform
    dependant - http://stackoverflow.com/questions/2609259/converting-string-t\
        o-datetime-object-in-python

    """
    match = timezone_re.match(date_string)
    if not match:
        raise ValueError(
            "{} fos not match the format 2014-01-16T12:07:23.322+03".format(
                date_string))

    date_time = match.groups()[0]
    tz = match.groups()[1]
    if len(tz) == 2:
        tz += '00'
    elif len(tz) != 4:
        raise ValueError("len of {} must either be 2 or 4")

    return "{}+{}".format(date_time, tz)


def find_choice_label(choices, string):
    for choice in choices:
        if choice['name'] == string:
            return choice['label']


def get_choice_label(choices, string):
    """
    `string` is the name value found in the choices sheet.

    Select one names should not contain spaces but some do and this conflicts
    with Select Multiple fields which use spaces to distinguish multiple
    choices.

    A temporal fix to this is to search the choices list for both the
    full-string and the split keys.
    """
    labels = []

    if string and choices:
        label = find_choice_label(choices, string)

        if label:
            labels.append(label)
        else:
            # the unsplit string doesn't exist as a key in choices.
            for name in string.split(" "):
                labels.append(find_choice_label(choices, name))

    elif not choices:
        labels = [string]

    return labels


def build_chart_data_for_field(xform, field, language_index=0, choices=None):
    # check if its the special _submission_time META
    if isinstance(field, basestring) and field == common_tags.SUBMISSION_TIME:
        field_label = 'Submission Time'
        field_xpath = '_submission_time'
        field_type = 'datetime'
    else:
        # TODO: merge choices with results and set 0's on any missing fields,
        # i.e. they didn't have responses

        # check if label is dict i.e. multilang
        if isinstance(field.label, dict) and len(field.label.keys()) > 0:
            languages = field.label.keys()
            language_index = min(language_index, len(languages) - 1)
            field_label = field.label[languages[language_index]]
        else:
            field_label = field.label or field.name

        field_xpath = field.get_abbreviated_xpath()
        field_type = field.type

    data_type = DATA_TYPE_MAP.get(field_type, 'categorized')
    field_name = field.name if not isinstance(field, basestring) else field

    result = get_form_submissions_grouped_by_field(
        xform, field_xpath, field_name)

    # truncate field name to 63 characters to fix #354
    truncated_name = field_name[0:POSTGRES_ALIAS_LENGTH]
    truncated_name = truncated_name.encode('utf-8')

    if data_type == 'categorized':
        if result:
            if field.children:
                choices = field.children

            for item in result:
                item[truncated_name] = get_choice_label(
                    choices, item[truncated_name])

    # replace truncated field names in the result set with the field name key
    field_name = field_name.encode('utf-8')

    for item in result:
        if field_name != truncated_name:
            item[field_name] = item[truncated_name]
            del(item[truncated_name])

    result = sorted(result, key=lambda d: d['count'])

    # for date fields, strip out None values
    if data_type == 'time_based':
        result = [r for r in result if r.get(field_name) is not None]
        # for each check if it matches the timezone regexp and convert for js
        for r in result:
            if timezone_re.match(r[field_name]):
                try:
                    r[field_name] = utc_time_string_for_javascript(
                        r[field_name])
                except ValueError:
                    pass

    return {
        'data': result,
        'data_type': data_type,
        'field_label': field_label,
        'field_xpath': field_name,
        'field_name': field_xpath.replace('/', '-'),
        'field_type': field_type
    }


def calculate_ranges(page, items_per_page, total_items):
    """Return the offset and end indices for a slice."""
    # offset  cannot be more than total_items
    offset = min(page * items_per_page, total_items)

    end = min(offset + items_per_page, total_items)
    # returns the offset and the end for a slice
    return offset, end


def build_chart_data(xform, language_index=0, page=0):
    dd = xform.data_dictionary()
    # only use chart-able fields

    fields = filter(
        lambda f: f.type in CHART_FIELDS, [e for e in dd.survey_elements])

    # prepend submission time
    fields[:0] = [common_tags.SUBMISSION_TIME]

    # get chart data for fields within this `page`
    start, end = calculate_ranges(page, CHARTS_PER_PAGE, len(fields))
    fields = fields[start:end]

    return [build_chart_data_for_field(xform, field, language_index)
            for field in fields]


def build_chart_data_from_widget(widget, language_index=0):

    if isinstance(widget.content_object, XForm):
        xform = widget.content_object
    elif isinstance(widget.content_object, DataView):
        xform = widget.content_object.xform
    else:
        raise ParseError("Model not supported")
    dd = xform.data_dictionary()

    field_name = widget.column

    # check if its the special _submission_time META
    if field_name == common_tags.SUBMISSION_TIME:
        field = common_tags.SUBMISSION_TIME
    else:
        # use specified field to get summary
        fields = filter(
            lambda f: f.name == field_name,
            [e for e in dd.survey_elements])

        if len(fields) == 0:
            raise ParseError(
                "Field %s does not not exist on the form" % field_name)

        field = fields[0]
    choices = dd.survey.get('choices')

    if choices:
        choices = choices.get(field_name)
    try:
        data = build_chart_data_for_field(
            xform, field, language_index, choices=choices)
    except DataError as e:
        raise ParseError(unicode(e))

    return data


def get_chart_data_for_field(field_name, xform, accepted_format, group_by):
    """
    Get chart data for a given xlsform field.
    """
    data = {}
    dd = xform.data_dictionary()
    # check if its the special _submission_time META
    if field_name == common_tags.SUBMISSION_TIME:
        field = common_tags.SUBMISSION_TIME
    else:
        # use specified field to get summary
        fields = filter(
            lambda f: f.name == field_name,
            [e for e in dd.survey_elements])

        if len(fields) == 0:
            raise Http404(
                "Field %s does not not exist on the form" % field_name)

        field = fields[0]
    choices = dd.survey.get('choices')

    if choices:
        choices = choices.get(field_name)

    try:
        data = build_chart_data_for_field(
            xform, field, choices=choices, group_by=group_by)
    except DataError as e:
        raise ParseError(unicode(e))
    else:
        if accepted_format == 'json':
            xform = xform.pk
        elif accepted_format == 'html' and 'data' in data:
            for item in data['data']:
                if isinstance(item[field_name], list):
                    item[field_name] = u', '.join(item[field_name])

        data.update({
            'xform': xform
        })

    return data
