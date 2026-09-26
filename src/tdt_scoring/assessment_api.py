"""Assessment scope and manager task endpoints."""
from io import BytesIO
from fastapi import APIRouter, HTTPException, Request
from zipfile import BadZipFile
from openpyxl.utils.exceptions import InvalidFileException
from fastapi.responses import StreamingResponse
from .assessment import match_roster, confirm_roster, roster_from_excel, assign_local_manager, tasks, exclude_task, require_selected
from .manager_evaluation import export_task, import_task
from .scoring_policy import load_policy
from .export_names import review_export_disposition
from .submission import EXCEL_MEDIA_TYPE
from .sources.local_excel import MAX_WORKBOOK_BYTES


def create_router(service, encode, workspace=None):
    router = APIRouter(prefix='/api/assessment')

    def run(action):
        try:
            with service._fact_lock: return action()
        except KeyError as exc: raise HTTPException(404, str(exc)) from None
        except (ValueError, TypeError) as exc: raise HTTPException(400, str(exc)) from None
        except (BadZipFile, InvalidFileException): raise HTTPException(400, '不是有效的Excel文件') from None

    @router.get('/policy')
    def policy(): return run(load_policy)

    @router.post('/roster-file')
    async def roster_file(request: Request, analysis_id: str):
        content = await request.body()
        if len(content) > MAX_WORKBOOK_BYTES: raise HTTPException(413, '名单文件超过30MB限制')
        return run(lambda: match_roster(service.get_analysis(analysis_id), roster_from_excel(content)))

    @router.post('/roster')
    async def roster(request: Request):
        data = await request.json()
        def action():
            if data.get('confirm'):
                with service.edit_analysis(data['analysis_id']) as analysis:
                    confirm_roster(analysis, data['names'], data.get('batch_id') or analysis.analysis_id, data.get('policy_hash'))
                    if workspace:
                        workspace.freeze_accounts(analysis)
                    return encode(analysis)
            analysis = service.get_analysis(data['analysis_id'])
            return match_roster(analysis, data['names'])
        return run(action)

    @router.post('/local-manager')
    async def local_manager(request: Request):
        data = await request.json()
        def action():
            with service.edit_analysis(data['analysis_id']) as analysis:
                name = data.get('name', '')
                if workspace:
                    user = workspace.store.user(data['manager_id'])
                    if not user: raise ValueError('请先在考核列表登记经理姓名与工号')
                    name = user['name']
                assign_local_manager(analysis, data['source_name'], data['manager_id'], name)
                return encode(analysis)
        return run(action)

    @router.get('/tasks')
    def task_list(analysis_id: str, request: Request):
        def action():
            analysis = service.get_analysis(analysis_id)
            if workspace:
                return workspace.task_list(analysis, workspace.authorize(request))
            return {**tasks(analysis), 'reviews': analysis.manager_reviews, 'exclusions': analysis.assessment.get('exclusions', {})}
        return run(action)

    @router.post('/exclude-task')
    async def exclude(request: Request):
        data = await request.json()
        def action():
            analysis = service.get_analysis(data['analysis_id'])
            exclude_task(analysis, data['manager_id'], data['expert_name'], data.get('reason', ''))
            return encode(analysis)
        return run(action)

    @router.get('/task-export')
    def task_export(analysis_id: str, manager_id: str):
        content = run(lambda: export_task(service.get_analysis(analysis_id), manager_id))
        return StreamingResponse(BytesIO(content), media_type=EXCEL_MEDIA_TYPE, headers={'Content-Disposition': review_export_disposition('经理问卷_'+manager_id, 'manager-questionnaire.xlsx')})

    @router.post('/task-import')
    async def task_import(request: Request, analysis_id: str):
        content = await request.body()
        if len(content) > MAX_WORKBOOK_BYTES: raise HTTPException(413, '问卷文件超过30MB限制')
        def action():
            analysis = service.get_analysis(analysis_id)
            require_selected(analysis)
            result = import_task(analysis, content)
            return {**result, 'analysis': encode(analysis)}
        return run(action)

    return router
