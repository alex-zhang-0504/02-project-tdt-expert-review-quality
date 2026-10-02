"""Derived local learning records; original model decisions remain untouched."""
import json


def learning_records(payloads):
    for payload in payloads:
        analysis = json.loads(payload)
        for expert in analysis.get('experts', []):
            for session in expert['sessions']:
                for opinion in session['opinions']:
                    for index, event in enumerate(opinion.get('audit', [])):
                        automatic = event.get('automatic_status')
                        value = event.get('to')
                        kind = ('historical_unknown' if automatic is None else 'reset' if value is None
                                else 'confirmation' if automatic == 'suspected'
                                else 'correction' if value != (automatic == 'yes') else 'agreement')
                        yield {'analysis_id': analysis['analysis_id'], 'task': analysis['source_name'],
                               'source_name': session['source_name'], 'project_code': session['project_code'],
                               'stage': session['stage'], 'reviewer': expert['expert_name'],
                               'opinion_id': opinion['opinion_id'], 'text': opinion['text'],
                               'cells': opinion.get('cells', []), 'event_index': index, 'kind': kind,
                               **event, 'current_included': opinion.get('included'),
                               'task_deleted': analysis.get('assessment', {}).get('deleted', False)}
