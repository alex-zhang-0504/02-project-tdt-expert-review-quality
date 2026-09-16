import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from tdt_scoring.import_batches import ImportBatches
from tdt_scoring.progress import ImportJobStore
from tdt_scoring.service import ScoringService
from tests.workbook_factory import build_v04_workbook


def report(code='B260001', stage='TDR1'):
    return build_v04_workbook([{'stage':stage}],project='虚拟项目-'+code)


class ImportBatchTests(unittest.TestCase):
    def setUp(self):
        self.service=ScoringService()
        self.jobs=ImportJobStore()
        self.executor=ThreadPoolExecutor(max_workers=2)
        self.runner=ImportBatches(self.service,self.jobs,self.executor)

    def tearDown(self):
        self.executor.shutdown(wait=True)

    def finish(self, job):
        for _ in range(500):
            result=self.jobs.snapshot(job.job_id)
            if result.status in {'completed','stopped','error'}:
                while self.runner.batches[job.job_id]['active']:
                    time.sleep(.001)
                self.assertNotEqual('error',result.status,result.error)
                return result
            time.sleep(.01)
        self.fail('import timeout')

    def test_replace_only_target_and_recheck_duplicates(self):
        with patch.object(self.service,'import_local_bytes', wraps=self.service.import_local_bytes) as read:
            job=self.runner.local([(report(),'a.xlsx'),(b'broken','b.xlsx')])
            first=self.finish(job)
            self.assertTrue(first.result.reports[1].issues)
            retry=self.runner.retry(job.job_id,1,(report('B260002'),'b.xlsx'))
            fixed=self.finish(retry)
            self.assertEqual(3,read.call_count)
            self.assertEqual(2,len(fixed.result.sessions))
            self.assertFalse([i for i in fixed.result.issues if i.severity=='error'])
            duplicate=self.finish(self.runner.retry(retry.job_id,1,(report(),'b.xlsx')))
            self.assertTrue(any(i.code=='cross_report_stage_duplicate' for i in duplicate.result.issues))

    def test_stop_keeps_finished_and_retry_unscanned(self):
        entered,release=Event(),Event()
        original=self.service.import_local_bytes
        def read(*args,**kwargs):
            entered.set()
            release.wait(3)
            return original(*args,**kwargs)
        with patch.object(self.service,'import_local_bytes', side_effect=read) as call:
            job=self.runner.local([(report(),'a.xlsx'),(report('B260002'),'b.xlsx')])
            self.assertTrue(entered.wait(2))
            with self.assertRaises(ValueError):
                self.runner.retry(job.job_id,0,(report(),'a.xlsx'))
            self.jobs.stop(job.job_id)
            release.set()
            stopped=self.finish(job)
            self.assertEqual('stopped',stopped.status)
            self.assertEqual(1,call.call_count)
            self.assertEqual(1,len(stopped.result.sessions))
            self.assertTrue(any(i.code=='report_not_scanned' for i in stopped.result.issues))
        done=self.finish(self.runner.retry(job.job_id,1,(report('B260002'),'b.xlsx')))
        self.assertFalse([i for i in done.result.issues if i.severity=='error'])

    def test_feishu_retry_uses_only_original_target(self):
        candidates=([{},{}],[('甲','token-a',None),('乙','token-b',None)],[0,0],[])
        with patch('tdt_scoring.import_batches.FeishuDocumentSource.folder_candidates',return_value=candidates), patch('tdt_scoring.import_batches.FeishuDocumentSource.export_xlsx',side_effect=[(report(),'x'),(b'broken','x'),(report('B260002'),'x')]) as export:
            job=self.runner.feishu('https://example.feishu.cn/drive/folder/folder-token')
            first=self.finish(job)
            done=self.finish(self.runner.retry(job.job_id,1))
            self.assertEqual(3,export.call_count)
            self.assertEqual('https://example.feishu.cn/sheets/token-b',export.call_args.args[0])
            self.assertTrue(done.result.batch_summary.complete)
            self.assertEqual(2,len(done.result.sessions))

    def test_retry_first_keeps_later_progress_while_reading(self):
        job=self.runner.local([(b'broken','a.xlsx'),(report('B260002'),'b.xlsx'),(b'broken','c.xlsx')])
        first=self.finish(job)
        entered, release=Event(), Event()
        original=self.service.import_local_bytes
        def read(*args, **kwargs):
            entered.set()
            release.wait(3)
            return original(*args, **kwargs)
        with patch.object(self.service,'import_local_bytes',side_effect=read) as call:
            retry=self.runner.retry(job.job_id,0,(report(),'a.xlsx'))
            self.assertTrue(entered.wait(2))
            snapshot=self.jobs.snapshot(retry.job_id)
            self.assertEqual(first.reports[1:],snapshot.reports[1:])
            release.set()
            done=self.finish(retry)
            self.assertEqual(1,call.call_count)
            self.assertEqual(first.reports[1:],done.reports[1:])
            self.assertTrue(any(i.severity=='error' for i in done.result.issues))

    def test_live_issue_and_parallel_rescan_before_batch_finishes(self):
        later_started, later_release, retry_started, retry_release = Event(), Event(), Event(), Event()
        original=self.service.import_local_bytes
        def read(content, name, **kwargs):
            if name == 'later.xlsx':
                later_started.set()
                later_release.wait(4)
            if name == 'fixed.xlsx':
                retry_started.set()
                retry_release.wait(4)
            return original(content,name,**kwargs)
        with patch.object(self.service,'import_local_bytes',side_effect=read) as call:
            job=self.runner.local([(b'broken','bad.xlsx'),(report('B260002'),'later.xlsx')])
            self.assertTrue(later_started.wait(2))
            live=self.jobs.snapshot(job.job_id)
            self.assertEqual('running',live.status)
            self.assertTrue(live.reports[0].ready)
            self.assertEqual('error',live.reports[0].status)
            self.assertTrue(live.reports[0].issues)
            retry=self.runner.retry(job.job_id,0,(report(),'fixed.xlsx'))
            self.assertEqual(job.job_id,retry.job_id)
            self.assertTrue(retry_started.wait(2))
            with self.assertRaises(ValueError): self.runner.retry(job.job_id,0,(report(),'fixed.xlsx'))
            later_release.set()
            self.assertEqual('running',self.jobs.snapshot(job.job_id).status)
            retry_release.set()
            done=self.finish(job)
            self.assertEqual(3,call.call_count)
            self.assertEqual(2,len(done.result.sessions))
            self.assertFalse([i for i in done.result.issues if i.severity=='error'])

    def test_cross_report_names_checked_at_final_and_refreshed_after_rescan(self):
        def named(name,code):
            return build_v04_workbook([{'stage':'TDR1','signoffs':[{'reviewer':name,'conclusion':'Go'}, {'reviewer':'虚拟专家甲','conclusion':'Go'}, {'reviewer':'虚拟专家乙','conclusion':'Go'}]}],project='虚拟项目-'+code)
        job=self.runner.local([(named('陈名木','B260001'),'a.xlsx'),(named('程名木','B260002'),'b.xlsx')])
        first=self.finish(job)
        self.assertTrue(any(i.code=='reviewer_name_similarity' for i in first.result.issues))
        self.assertFalse(any(i.code=='reviewer_name_similarity' for r in first.reports for i in r.issues))
        done=self.finish(self.runner.retry(job.job_id,1,(named('陈名木','B260002'),'fixed.xlsx')))
        self.assertFalse(any(i.code=='reviewer_name_similarity' for i in done.result.issues))

    def test_invalid_extension_and_missing_replacement(self):
        job=self.runner.local([(report(),'a.txt')])
        result=self.finish(job)
        self.assertTrue(any(i.severity=='error' for i in result.result.issues))
        with self.assertRaises(ValueError):
            self.runner.retry(job.job_id,0)
        done=self.finish(self.runner.retry(job.job_id,0,(report(),'fixed.xlsx')))
        self.assertFalse([i for i in done.result.issues if i.severity=='error'])
