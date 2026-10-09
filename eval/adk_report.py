"""Summarize actual ADK result files; never publish opaque model trace metadata."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
files = sorted((ROOT / 'api/agents/goldenhour_agent/.adk/eval_history').glob('*.evalset_result.json'))
if not files:
    raise SystemExit('Run adk eval first: no measured results exist.')
rows = []
for path in files:
    data = json.loads(path.read_text())
    cases = []
    for case in data['eval_case_results']:
        inv = case['eval_metric_result_per_invocation'][0]
        events = inv['actual_invocation'].get('intermediate_data', {}).get('invocation_events', [])
        calls = [part['function_call'] for event in events for part in (event.get('content') or {}).get('parts', []) if part.get('function_call')]
        expected = 'MY' if case['eval_id'].startswith('malaysia') else 'IN'
        correct_country = all(call.get('args', {}).get('country', None if call['name'] == 'get_helplines' else 'IN') == expected for call in calls if call['name'] in ['get_helplines', 'check_if_scam', 'start_case'])
        metrics = [{key: metric[key] for key in ['metric_name', 'score', 'threshold', 'eval_status']} for metric in case['overall_eval_metric_results']]
        cases.append({'id':case['eval_id'], 'overall_status':case['final_eval_status'], 'metrics':metrics, 'country_arguments_correct':correct_country,
                      'tool_names':[call['name'] for call in calls], 'response':''.join(part.get('text') or '' for part in inv['actual_invocation']['final_response'].get('parts', []) if not part.get('thought'))})
    rows.append({'run':path.name,'created_at':data['creation_timestamp'],'cases':cases})
(ROOT/'eval/adk_results.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False))
lines = ['# ADK guidance evaluation', '', 'Actual five-case Google-model runs. Agent and judge: Gemini 3.8 Flash on Vertex AI (`us`). Each judge criterion uses three samples. This small text set does not establish physical-device or general safety performance.', '', 'The initial strict EXACT trajectory run failed all five because it compared extra helpful tools and paraphrased arguments against a single exact reference call. Safety and final-response judges passed all five. The updated criterion requires expected tool names in order, allows extra tools and ignores wording differences in arguments. Country arguments are checked separately below. Initial results remain in the JSON report.', '', '| Latest case | Tool criterion | Response match | Safety rubric | Country arguments |', '|---|---|---|---|---|']
for case in rows[-1]['cases']:
    metrics = {m['metric_name']:m for m in case['metrics']}
    lines.append('| '+case['id']+' | '+' | '.join(str(metrics[name]['score']) for name in ['tool_trajectory_avg_score','final_response_match_v2','rubric_based_final_response_quality_v1'])+' | '+str(case['country_arguments_correct'])+' |')
lines += ['', 'PASS status is ADK enum 1; FAIL is enum 2. See `adk_results.json` for measured scores, thresholds and responses. No automatic filing or real bank integration is tested.']
(ROOT/'eval/report_adk.md').write_text('\n'.join(lines)+'\n')
print('\n'.join(lines[4:]))
