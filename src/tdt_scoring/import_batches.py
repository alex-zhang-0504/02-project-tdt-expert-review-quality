"""Per-report import cache, replacement, and cooperative stop."""
from copy import deepcopy
from threading import RLock
from urllib.parse import urlparse
from .models import BatchImportSummary, ValidationIssue
from .progress import ProgressEvent
from .sources.feishu_document import FeishuDocumentSource


class ImportBatches:
    def __init__(self, service, jobs, executor):
        self.service, self.jobs, self.executor = service, jobs, executor
        self.batches = {}
        self.lock = RLock()

    def local(self, uploads):
        entries = [dict(name=name, content=content, url=None, parsed=None) for content, name in uploads]
        return self.start(dict(entries=entries, source='local_excel', active=False))

    def feishu(self, url):
        return self.start(dict(entries=[], source='feishu_folder' if FeishuDocumentSource.is_folder_url(url) else 'feishu_document', url=url, active=False))

    def start(self, batch, target=None, previous_id=None):
        with self.lock:
            if batch['active']:
                raise ValueError('该批次正在读取，请先停止或等待完成')
            batch['active'] = True
            batch['workers'] = 1
            if target is not None:
                batch['entries'][target]['busy'] = True
            job = self.jobs.create(batch['source'])
            if previous_id is not None:
                self.jobs.seed_retry(job.job_id, previous_id, target)
            self.batches[job.job_id] = batch
            batch['job_id'] = job.job_id
        self.executor.submit(self.run, job.job_id, batch, target)
        return job

    def retry(self, job_id, index, upload=None):
        with self.lock:
            batch = self.batches[job_id]
            if not 0 <= index < len(batch['entries']):
                raise ValueError('报告不存在')
            entry = batch['entries'][index]
            if batch['active'] and (entry.get('busy') or entry['parsed'] is None):
                raise ValueError('此报告尚未完成当前扫描，请等待后再重扫')
            if batch['active'] and self.jobs.stopping(batch['job_id']):
                raise ValueError('正在停止读取，请停止后再重扫')
            if batch['source'] == 'local_excel' and upload is None:
                raise ValueError('请重新选择已修改的本地报告')
            if upload is not None:
                if not upload[1].lower().endswith('.xlsx'):
                    raise ValueError('仅支持.xlsx报告')
                entry['content'] = upload[0]
                entry['filename'] = upload[1]
            # Keep the batch identity even if a replacement file has a different name.
            if batch['active']:
                active_id = batch['job_id']
                entry['busy'] = True
                batch['workers'] += 1
                self.jobs.reset_report(active_id, index)
                self.executor.submit(self.rescan, active_id, batch, index)
                return self.jobs.snapshot(active_id)
            return self.start(batch, index, job_id)

    def discover(self, batch):
        if batch['source'] == 'feishu_folder':
            items, candidates, _, excluded = FeishuDocumentSource.folder_candidates(batch['url'])
            batch['summary'] = BatchImportSummary(len(items), len(candidates), 0, 0, len(excluded), False, excluded)
            batch['entries'] = [dict(name=name, content=None, url=f'https://{urlparse(batch["url"]).hostname}/sheets/{token}' if token else None,
                                     error=error, parsed=None) for name, token, error in candidates]
        else:
            batch['entries'] = [dict(name='tdrx-review.xlsx', content=None, url=batch['url'], parsed=None)]

    def run(self, job_id, batch, target):
        self.jobs.start(job_id)
        try:
            if not batch['entries'] and 'url' in batch:
                self.discover(batch)
            entries = batch['entries']
            self.jobs.set_reports(job_id, [e['name'] for e in entries])
            for index, entry in enumerate(entries):
                if target is not None and index != target:
                    continue
                if self.jobs.stopping(job_id):
                    break
                with self.lock:
                    entry['busy'] = True
                self.read_one(job_id, batch, index)
        except Exception as exc:
            self.jobs.fail(job_id, str(exc))
        finally:
            self.finish_worker(job_id, batch)

    def read_one(self, job_id, batch, index):
        entry = batch['entries'][index]
        try:
            if entry.get('error'):
                raise ValueError(entry['error'])
            content = entry['content']
            if entry['url']:
                self.jobs.record(job_id, ProgressEvent(entry['name'], 'xlsx_acquisition', 'started'))
                content, _ = FeishuDocumentSource.export_xlsx(entry['url'])
            filename = entry.get('filename', entry['name'])
            if batch['source'] != 'local_excel' and not filename.endswith('.xlsx'):
                filename += '.xlsx'
            result = self.service.import_local_bytes(content, filename,
                progress=lambda event: self.jobs.record(job_id, ProgressEvent(entry['name'], event.checkpoint_id, event.status, event.duration_ms, event.message)))
            for session in result.sessions:
                session.source_name = entry['name']
            issues = [i for i in result.issues if i.code != 'reviewer_name_similarity']
            for issue in issues:
                issue.source_name = entry['name']
            parsed = (result.sessions, issues)
        except Exception as exc:
            parsed = ([], [ValidationIssue('report_read_failed', str(exc), 'error', source_name=entry['name'])])
            self.jobs.record(job_id, ProgressEvent(entry['name'], 'workbook_parse', 'error', message=str(exc)))
        with self.lock:
            entry['parsed'] = parsed
            self.jobs.report_result(job_id, index, parsed[1])
            entry['busy'] = False

    def rescan(self, job_id, batch, index):
        try:
            # A queued rescan is skipped after stop; retain its earlier parsed result.
            if not self.jobs.stopping(job_id):
                self.read_one(job_id, batch, index)
            else:
                with self.lock:
                    batch['entries'][index]['busy'] = False
        finally:
            self.finish_worker(job_id, batch)

    def finish_worker(self, job_id, batch):
        with self.lock:
            batch['workers'] -= 1
            if batch['workers']:
                return
            try:
                if self.jobs.snapshot(job_id).status == 'error':
                    return
                entries = batch['entries']
                cached = {index: entry['parsed'] or ([], [ValidationIssue('report_not_scanned', '尚未扫描，请单独检查此报告', 'error', source_name=entry['name'])])
                          for index, entry in enumerate(entries)}
                result = self.service._analyze_many([(None, e['name'], []) for e in entries],
                    source_type=batch['source'], source_name=f"{len(entries)}份评审报告",
                    parsed_reports=cached, batch_summary=deepcopy(batch.get('summary')))
                self.jobs.complete(job_id, result)
            except Exception as exc:
                self.jobs.fail(job_id, str(exc))
            finally:
                batch['active'] = False
