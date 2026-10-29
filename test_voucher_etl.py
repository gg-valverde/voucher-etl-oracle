import unittest
from datetime import timedelta
from unittest.mock import Mock, patch
import voucher_etl as etl

class VoucherTests(unittest.TestCase):
    def test_date_crosses_previous_day_in_bolivia(self):
        day = etl.convertir_fecha('2026-01-02T02:30:00Z')
        self.assertEqual(day.isoformat(), '2026-01-01T22:30:00-04:00')

    def test_fractional_seconds_and_null_dates(self):
        self.assertEqual(etl.convertir_fecha('2026-01-03T15:20:10.57692Z').microsecond, 576920)
        self.assertEqual(etl.convertir_fecha('2026-01-03T15:20:10').utcoffset(), timedelta(hours=-4))
        self.assertIsNone(etl.convertir_fecha(None))
        with patch('builtins.print'):
            self.assertIsNone(etl.convertir_fecha('fecha-invalida'))

    def test_batch_loading_commits_each_chunk_and_tags_run(self):
        cursor, conn = Mock(), Mock()
        rows = [{'id': str(i)} for i in range(5)]
        with patch.object(etl, 'ORACLE_BATCH_SIZE', 2):
            self.assertEqual(etl.cargar_lote(cursor, conn, rows, 'demo-run'), 5)
        self.assertEqual(cursor.executemany.call_count, 3)
        self.assertEqual(conn.commit.call_count, 3)
        self.assertTrue(all(r['run_id'] == 'demo-run' for r in rows))

    def test_retry_after_temporary_failure(self):
        session = Mock()
        response = Mock(); response.json.return_value = [{'id':'DEMO'}]
        session.get.side_effect = [TimeoutError('simulated'), response]
        with patch('time.sleep') as sleep, patch('builtins.print'):
            result = etl.obtener_pagina(session, 'fake-token', '2026-01-01', '2026-01-31', 100, 1)
        self.assertEqual(result, [{'id':'DEMO'}])
        self.assertEqual(session.get.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_pagination_and_missing_id_stops_before_loading(self):
        cursor, conn = Mock(), Mock()
        kwargs = dict(session=Mock(),token='fake',cursor=cursor,connection=conn,
                      voucher_config=100,campana_voucher='Ficticia',fecha_inicio='2026-01-01',fecha_fin='2026-01-31',run_id='demo')
        with patch.object(etl,'PAGE_LENGTH',2), patch.object(etl,'obtener_pagina',side_effect=[[{'id':'A'},{'id':'B'}],[{'id':'C'}]]) as get, patch('builtins.print'):
            self.assertEqual(etl.procesar_campana(**kwargs),(3,3))
            self.assertEqual(get.call_count,2)
        cursor.reset_mock()
        with patch.object(etl,'obtener_pagina',return_value=[{'amount':25}]), patch('builtins.print'), self.assertRaises(ValueError):
            etl.procesar_campana(**kwargs)
        cursor.executemany.assert_not_called()

if __name__ == '__main__':
    unittest.main()
