import falcon
import simplejson as json
import mysql.connector
import config
from datetime import datetime, timedelta, timezone
from core import utilities
from decimal import Decimal
import excelexporters.tenantenergyitem


class Reporting:
    @staticmethod
    def __init__():
        pass

    @staticmethod
    def on_options(req, resp):
        resp.status = falcon.HTTP_200

    ####################################################################################################################
    # PROCEDURES
    # Step 1: valid parameters
    # Step 2: query the tenant
    # Step 3: query energy items
    # Step 4: query associated sensors
    # Step 5: query associated points
    # Step 6: query base period energy input
    # Step 7: query reporting period energy input
    # Step 8: query tariff data
    # Step 9: query associated sensors and points data
    # Step 10: construct the report
    ####################################################################################################################
    @staticmethod
    def on_get(req, resp):
        print(req.params)
        tenant_id = req.params.get('tenantid')
        period_type = req.params.get('periodtype')
        base_start_datetime_local = req.params.get('baseperiodstartdatetime')
        base_end_datetime_local = req.params.get('baseperiodenddatetime')
        reporting_start_datetime_local = req.params.get('reportingperiodstartdatetime')
        reporting_end_datetime_local = req.params.get('reportingperiodenddatetime')

        ################################################################################################################
        # Step 1: valid parameters
        ################################################################################################################
        if tenant_id is None:
            raise falcon.HTTPError(falcon.HTTP_400, title='API.BAD_REQUEST', description='API.INVALID_TENANT_ID')
        else:
            tenant_id = str.strip(tenant_id)
            if not tenant_id.isdigit() or int(tenant_id) <= 0:
                raise falcon.HTTPError(falcon.HTTP_400, title='API.BAD_REQUEST', description='API.INVALID_TENANT_ID')

        if period_type is None:
            raise falcon.HTTPError(falcon.HTTP_400, title='API.BAD_REQUEST', description='API.INVALID_PERIOD_TYPE')
        else:
            period_type = str.strip(period_type)
            if period_type not in ['hourly', 'daily', 'monthly', 'yearly']:
                raise falcon.HTTPError(falcon.HTTP_400, title='API.BAD_REQUEST', description='API.INVALID_PERIOD_TYPE')

        timezone_offset = int(config.utc_offset[1:3]) * 60 + int(config.utc_offset[4:6])
        if config.utc_offset[0] == '-':
            timezone_offset = -timezone_offset

        base_start_datetime_utc = None
        if base_start_datetime_local is not None and len(str.strip(base_start_datetime_local)) > 0:
            base_start_datetime_local = str.strip(base_start_datetime_local)
            try:
                base_start_datetime_utc = datetime.strptime(base_start_datetime_local,
                                                            '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc) - \
                    timedelta(minutes=timezone_offset)
            except ValueError:
                raise falcon.HTTPError(falcon.HTTP_400, title='API.BAD_REQUEST',
                                       description="API.INVALID_BASE_PERIOD_START_DATETIME")

        base_end_datetime_utc = None
        if base_end_datetime_local is not None and len(str.strip(base_end_datetime_local)) > 0:
            base_end_datetime_local = str.strip(base_end_datetime_local)
            try:
                base_end_datetime_utc = datetime.strptime(base_end_datetime_local,
                                                          '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc) - \
                    timedelta(minutes=timezone_offset)
            except ValueError:
                raise falcon.HTTPError(falcon.HTTP_400, title='API.BAD_REQUEST',
                                       description="API.INVALID_BASE_PERIOD_END_DATETIME")

        if base_start_datetime_utc is not None and base_end_datetime_utc is not None and \
                base_start_datetime_utc >= base_end_datetime_utc:
            raise falcon.HTTPError(falcon.HTTP_400, title='API.BAD_REQUEST',
                                   description='API.INVALID_BASE_PERIOD_END_DATETIME')

        if reporting_start_datetime_local is None:
            raise falcon.HTTPError(falcon.HTTP_400, title='API.BAD_REQUEST',
                                   description="API.INVALID_REPORTING_PERIOD_START_DATETIME")
        else:
            reporting_start_datetime_local = str.strip(reporting_start_datetime_local)
            try:
                reporting_start_datetime_utc = datetime.strptime(reporting_start_datetime_local,
                                                                 '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc) - \
                    timedelta(minutes=timezone_offset)
            except ValueError:
                raise falcon.HTTPError(falcon.HTTP_400, title='API.BAD_REQUEST',
                                       description="API.INVALID_REPORTING_PERIOD_START_DATETIME")

        if reporting_end_datetime_local is None:
            raise falcon.HTTPError(falcon.HTTP_400, title='API.BAD_REQUEST',
                                   description="API.INVALID_REPORTING_PERIOD_END_DATETIME")
        else:
            reporting_end_datetime_local = str.strip(reporting_end_datetime_local)
            try:
                reporting_end_datetime_utc = datetime.strptime(reporting_end_datetime_local,
                                                               '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc) - \
                    timedelta(minutes=timezone_offset)
            except ValueError:
                raise falcon.HTTPError(falcon.HTTP_400, title='API.BAD_REQUEST',
                                       description="API.INVALID_REPORTING_PERIOD_END_DATETIME")

        if reporting_start_datetime_utc >= reporting_end_datetime_utc:
            raise falcon.HTTPError(falcon.HTTP_400, title='API.BAD_REQUEST',
                                   description='API.INVALID_REPORTING_PERIOD_END_DATETIME')

        ################################################################################################################
        # Step 2: query the tenant
        ################################################################################################################
        cnx_system = mysql.connector.connect(**config.myems_system_db)
        cursor_system = cnx_system.cursor()

        cnx_energy = mysql.connector.connect(**config.myems_energy_db)
        cursor_energy = cnx_energy.cursor()

        cnx_historical = mysql.connector.connect(**config.myems_historical_db)
        cursor_historical = cnx_historical.cursor()

        cursor_system.execute(" SELECT id, name, area, cost_center_id "
                              " FROM tbl_tenants "
                              " WHERE id = %s ", (tenant_id,))
        row_tenant = cursor_system.fetchone()
        if row_tenant is None:
            if cursor_system:
                cursor_system.close()
            if cnx_system:
                cnx_system.disconnect()

            if cursor_energy:
                cursor_energy.close()
            if cnx_energy:
                cnx_energy.disconnect()

            if cnx_historical:
                cnx_historical.close()
            if cursor_historical:
                cursor_historical.disconnect()
            raise falcon.HTTPError(falcon.HTTP_404, title='API.NOT_FOUND', description='API.TENANT_NOT_FOUND')

        tenant = dict()
        tenant['id'] = row_tenant[0]
        tenant['name'] = row_tenant[1]
        tenant['area'] = row_tenant[2]
        tenant['cost_center_id'] = row_tenant[3]

        ################################################################################################################
        # Step 3: query energy items
        ################################################################################################################
        energy_item_set = set()
        # query energy items in base period
        cursor_energy.execute(" SELECT DISTINCT(energy_item_id) "
                              " FROM tbl_tenant_input_item_hourly "
                              " WHERE tenant_id = %s "
                              "     AND start_datetime_utc >= %s "
                              "     AND start_datetime_utc < %s ",
                              (tenant['id'], base_start_datetime_utc, base_end_datetime_utc))
        rows_energy_items = cursor_energy.fetchall()
        if rows_energy_items is not None or len(rows_energy_items) > 0:
            for row_item in rows_energy_items:
                energy_item_set.add(row_item[0])

        # query energy items in reporting period
        cursor_energy.execute(" SELECT DISTINCT(energy_item_id) "
                              " FROM tbl_tenant_input_item_hourly "
                              " WHERE tenant_id = %s "
                              "     AND start_datetime_utc >= %s "
                              "     AND start_datetime_utc < %s ",
                              (tenant['id'], reporting_start_datetime_utc, reporting_end_datetime_utc))
        rows_energy_items = cursor_energy.fetchall()
        if rows_energy_items is not None or len(rows_energy_items) > 0:
            for row_item in rows_energy_items:
                energy_item_set.add(row_item[0])

        # query all energy items in base period and reporting period
        cursor_system.execute(" SELECT ei.id, ei.name, ei.energy_category_id, "
                              "        ec.name AS energy_category_name, ec.unit_of_measure, ec.kgce, ec.kgco2e "
                              " FROM tbl_energy_items ei, tbl_energy_categories ec "
                              " WHERE ei.energy_category_id = ec.id "
                              " ORDER BY ei.id ", )
        rows_energy_items = cursor_system.fetchall()
        if rows_energy_items is None or len(rows_energy_items) == 0:
            if cursor_system:
                cursor_system.close()
            if cnx_system:
                cnx_system.disconnect()

            if cursor_energy:
                cursor_energy.close()
            if cnx_energy:
                cnx_energy.disconnect()

            if cnx_historical:
                cnx_historical.close()
            if cursor_historical:
                cursor_historical.disconnect()
            raise falcon.HTTPError(falcon.HTTP_404,
                                   title='API.NOT_FOUND',
                                   description='API.ENERGY_ITEM_NOT_FOUND')
        energy_item_dict = dict()
        for row_energy_item in rows_energy_items:
            if row_energy_item[0] in energy_item_set:
                energy_item_dict[row_energy_item[0]] = {"name": row_energy_item[1],
                                                        "energy_category_id": row_energy_item[2],
                                                        "energy_category_name": row_energy_item[3],
                                                        "unit_of_measure": row_energy_item[4],
                                                        "kgce": row_energy_item[5],
                                                        "kgco2e": row_energy_item[6]}

        ################################################################################################################
        # Step 4: query associated sensors
        ################################################################################################################
        point_list = list()
        cursor_system.execute(" SELECT p.id, p.name, p.units, p.object_type  "
                              " FROM tbl_tenants t, tbl_sensors s, tbl_tenants_sensors ts, "
                              "      tbl_points p, tbl_sensors_points sp "
                              " WHERE t.id = %s AND t.id = ts.tenant_id AND ts.sensor_id = s.id "
                              "       AND s.id = sp.sensor_id AND sp.point_id = p.id "
                              " ORDER BY p.id ", (tenant['id'], ))
        rows_points = cursor_system.fetchall()
        if rows_points is not None and len(rows_points) > 0:
            for row in rows_points:
                point_list.append({"id": row[0], "name": row[1], "units": row[2], "object_type": row[3]})

        ################################################################################################################
        # Step 5: query associated points
        ################################################################################################################
        cursor_system.execute(" SELECT po.id, po.name, po.units, po.object_type  "
                              " FROM tbl_tenants sp, tbl_tenants_points sppo, tbl_points po "
                              " WHERE sp.id = %s AND sp.id = sppo.tenant_id AND sppo.point_id = po.id "
                              " ORDER BY po.id ", (tenant['id'], ))
        rows_points = cursor_system.fetchall()
        if rows_points is not None and len(rows_points) > 0:
            for row in rows_points:
                point_list.append({"id": row[0], "name": row[1], "units": row[2], "object_type": row[3]})

        ################################################################################################################
        # Step 6: query base period energy input
        ################################################################################################################
        base = dict()
        if energy_item_set is not None and len(energy_item_set) > 0:
            for energy_item_id in energy_item_set:
                base[energy_item_id] = dict()
                base[energy_item_id]['timestamps'] = list()
                base[energy_item_id]['values'] = list()
                base[energy_item_id]['subtotal'] = Decimal(0.0)

                cursor_energy.execute(" SELECT start_datetime_utc, actual_value "
                                      " FROM tbl_tenant_input_item_hourly "
                                      " WHERE tenant_id = %s "
                                      "     AND energy_item_id = %s "
                                      "     AND start_datetime_utc >= %s "
                                      "     AND start_datetime_utc < %s "
                                      " ORDER BY start_datetime_utc ",
                                      (tenant['id'],
                                       energy_item_id,
                                       base_start_datetime_utc,
                                       base_end_datetime_utc))
                rows_tenant_hourly = cursor_energy.fetchall()

                rows_tenant_periodically = utilities.aggregate_hourly_data_by_period(rows_tenant_hourly,
                                                                                     base_start_datetime_utc,
                                                                                     base_end_datetime_utc,
                                                                                     period_type)
                for row_tenant_periodically in rows_tenant_periodically:
                    current_datetime_local = row_tenant_periodically[0].replace(tzinfo=timezone.utc) + \
                                             timedelta(minutes=timezone_offset)
                    if period_type == 'hourly':
                        current_datetime = current_datetime_local.strftime('%Y-%m-%dT%H:%M:%S')
                    elif period_type == 'daily':
                        current_datetime = current_datetime_local.strftime('%Y-%m-%d')
                    elif period_type == 'monthly':
                        current_datetime = current_datetime_local.strftime('%Y-%m')
                    elif period_type == 'yearly':
                        current_datetime = current_datetime_local.strftime('%Y')

                    actual_value = Decimal(0.0) if row_tenant_periodically[1] is None else row_tenant_periodically[1]
                    base[energy_item_id]['timestamps'].append(current_datetime)
                    base[energy_item_id]['values'].append(actual_value)
                    base[energy_item_id]['subtotal'] += actual_value

        ################################################################################################################
        # Step 7: query reporting period energy input
        ################################################################################################################
        reporting = dict()
        if energy_item_set is not None and len(energy_item_set) > 0:
            for energy_item_id in energy_item_set:
                reporting[energy_item_id] = dict()
                reporting[energy_item_id]['timestamps'] = list()
                reporting[energy_item_id]['values'] = list()
                reporting[energy_item_id]['subtotal'] = Decimal(0.0)
                reporting[energy_item_id]['toppeak'] = Decimal(0.0)
                reporting[energy_item_id]['onpeak'] = Decimal(0.0)
                reporting[energy_item_id]['midpeak'] = Decimal(0.0)
                reporting[energy_item_id]['offpeak'] = Decimal(0.0)

                cursor_energy.execute(" SELECT start_datetime_utc, actual_value "
                                      " FROM tbl_tenant_input_item_hourly "
                                      " WHERE tenant_id = %s "
                                      "     AND energy_item_id = %s "
                                      "     AND start_datetime_utc >= %s "
                                      "     AND start_datetime_utc < %s "
                                      " ORDER BY start_datetime_utc ",
                                      (tenant['id'],
                                       energy_item_id,
                                       reporting_start_datetime_utc,
                                       reporting_end_datetime_utc))
                rows_tenant_hourly = cursor_energy.fetchall()

                rows_tenant_periodically = utilities.aggregate_hourly_data_by_period(rows_tenant_hourly,
                                                                                     reporting_start_datetime_utc,
                                                                                     reporting_end_datetime_utc,
                                                                                     period_type)
                for row_tenant_periodically in rows_tenant_periodically:
                    current_datetime_local = row_tenant_periodically[0].replace(tzinfo=timezone.utc) + \
                                             timedelta(minutes=timezone_offset)
                    if period_type == 'hourly':
                        current_datetime = current_datetime_local.strftime('%Y-%m-%dT%H:%M:%S')
                    elif period_type == 'daily':
                        current_datetime = current_datetime_local.strftime('%Y-%m-%d')
                    elif period_type == 'monthly':
                        current_datetime = current_datetime_local.strftime('%Y-%m')
                    elif period_type == 'yearly':
                        current_datetime = current_datetime_local.strftime('%Y')

                    actual_value = Decimal(0.0) if row_tenant_periodically[1] is None else row_tenant_periodically[1]
                    reporting[energy_item_id]['timestamps'].append(current_datetime)
                    reporting[energy_item_id]['values'].append(actual_value)
                    reporting[energy_item_id]['subtotal'] += actual_value

                energy_category_tariff_dict = \
                    utilities.get_energy_category_peak_types(tenant['cost_center_id'],
                                                             energy_item_dict[energy_item_id]['energy_category_id'],
                                                             reporting_start_datetime_utc,
                                                             reporting_end_datetime_utc)
                for row in rows_tenant_hourly:
                    peak_type = energy_category_tariff_dict.get(row[0], None)
                    if peak_type == 'toppeak':
                        reporting[energy_item_id]['toppeak'] += row[1]
                    elif peak_type == 'onpeak':
                        reporting[energy_item_id]['onpeak'] += row[1]
                    elif peak_type == 'midpeak':
                        reporting[energy_item_id]['midpeak'] += row[1]
                    elif peak_type == 'offpeak':
                        reporting[energy_item_id]['offpeak'] += row[1]

        ################################################################################################################
        # Step 8: query tariff data
        ################################################################################################################
        parameters_data = dict()
        parameters_data['names'] = list()
        parameters_data['timestamps'] = list()
        parameters_data['values'] = list()
        if energy_item_set is not None and len(energy_item_set) > 0:
            for energy_item_id in energy_item_set:
                energy_category_tariff_dict = \
                    utilities.get_energy_category_tariffs(tenant['cost_center_id'],
                                                          energy_item_dict[energy_item_id]['energy_category_id'],
                                                          reporting_start_datetime_utc,
                                                          reporting_end_datetime_utc)
                tariff_timestamp_list = list()
                tariff_value_list = list()
                for k, v in energy_category_tariff_dict.items():
                    # convert k from utc to local
                    k = k + timedelta(minutes=timezone_offset)
                    tariff_timestamp_list.append(k.isoformat()[0:19][0:19])
                    tariff_value_list.append(v)

                parameters_data['names'].append('TARIFF-' + energy_item_dict[energy_item_id]['name'])
                parameters_data['timestamps'].append(tariff_timestamp_list)
                parameters_data['values'].append(tariff_value_list)

        ################################################################################################################
        # Step 9: query associated sensors and points data
        ################################################################################################################
        for point in point_list:
            point_values = []
            point_timestamps = []
            if point['object_type'] == 'ANALOG_VALUE':
                query = (" SELECT utc_date_time, actual_value "
                         " FROM tbl_analog_value "
                         " WHERE point_id = %s "
                         "       AND utc_date_time BETWEEN %s AND %s "
                         " ORDER BY utc_date_time ")
                cursor_historical.execute(query, (point['id'],
                                                  reporting_start_datetime_utc,
                                                  reporting_end_datetime_utc))
                rows = cursor_historical.fetchall()

                if rows is not None and len(rows) > 0:
                    for row in rows:
                        current_datetime_local = row[0].replace(tzinfo=timezone.utc) + \
                                                 timedelta(minutes=timezone_offset)
                        current_datetime = current_datetime_local.strftime('%Y-%m-%dT%H:%M:%S')
                        point_timestamps.append(current_datetime)
                        point_values.append(row[1])

            elif point['object_type'] == 'ENERGY_VALUE':
                query = (" SELECT utc_date_time, actual_value "
                         " FROM tbl_energy_value "
                         " WHERE point_id = %s "
                         "       AND utc_date_time BETWEEN %s AND %s "
                         " ORDER BY utc_date_time ")
                cursor_historical.execute(query, (point['id'],
                                                  reporting_start_datetime_utc,
                                                  reporting_end_datetime_utc))
                rows = cursor_historical.fetchall()

                if rows is not None and len(rows) > 0:
                    for row in rows:
                        current_datetime_local = row[0].replace(tzinfo=timezone.utc) + \
                                                 timedelta(minutes=timezone_offset)
                        current_datetime = current_datetime_local.strftime('%Y-%m-%dT%H:%M:%S')
                        point_timestamps.append(current_datetime)
                        point_values.append(row[1])
            elif point['object_type'] == 'DIGITAL_VALUE':
                query = (" SELECT utc_date_time, actual_value "
                         " FROM tbl_digital_value "
                         " WHERE point_id = %s "
                         "       AND utc_date_time BETWEEN %s AND %s ")
                cursor_historical.execute(query, (point['id'],
                                                  reporting_start_datetime_utc,
                                                  reporting_end_datetime_utc))
                rows = cursor_historical.fetchall()

                if rows is not None and len(rows) > 0:
                    for row in rows:
                        current_datetime_local = row[0].replace(tzinfo=timezone.utc) + \
                                                 timedelta(minutes=timezone_offset)
                        current_datetime = current_datetime_local.strftime('%Y-%m-%dT%H:%M:%S')
                        point_timestamps.append(current_datetime)
                        point_values.append(row[1])

            parameters_data['names'].append(point['name'] + ' (' + point['units'] + ')')
            parameters_data['timestamps'].append(point_timestamps)
            parameters_data['values'].append(point_values)

        ################################################################################################################
        # Step 10: construct the report
        ################################################################################################################
        if cursor_system:
            cursor_system.close()
        if cnx_system:
            cnx_system.disconnect()

        if cursor_energy:
            cursor_energy.close()
        if cnx_energy:
            cnx_energy.disconnect()

        if cnx_historical:
            cnx_historical.close()
        if cursor_historical:
            cursor_historical.disconnect()

        result = dict()

        result['tenant'] = dict()
        result['tenant']['name'] = tenant['name']
        result['tenant']['area'] = tenant['area']

        result['base_period'] = dict()
        result['base_period']['names'] = list()
        result['base_period']['units'] = list()
        result['base_period']['timestamps'] = list()
        result['base_period']['values'] = list()
        result['base_period']['subtotals'] = list()
        if energy_item_set is not None and len(energy_item_set) > 0:
            for energy_item_id in energy_item_set:
                result['base_period']['names'].append(energy_item_dict[energy_item_id]['name'])
                result['base_period']['units'].append(energy_item_dict[energy_item_id]['unit_of_measure'])
                result['base_period']['timestamps'].append(base[energy_item_id]['timestamps'])
                result['base_period']['values'].append(base[energy_item_id]['values'])
                result['base_period']['subtotals'].append(base[energy_item_id]['subtotal'])

        result['reporting_period'] = dict()
        result['reporting_period']['names'] = list()
        result['reporting_period']['energy_item_ids'] = list()
        result['reporting_period']['energy_category_names'] = list()
        result['reporting_period']['energy_category_ids'] = list()
        result['reporting_period']['units'] = list()
        result['reporting_period']['timestamps'] = list()
        result['reporting_period']['values'] = list()
        result['reporting_period']['subtotals'] = list()
        result['reporting_period']['subtotals_per_unit_area'] = list()
        result['reporting_period']['toppeaks'] = list()
        result['reporting_period']['onpeaks'] = list()
        result['reporting_period']['midpeaks'] = list()
        result['reporting_period']['offpeaks'] = list()
        result['reporting_period']['increment_rates'] = list()

        if energy_item_set is not None and len(energy_item_set) > 0:
            for energy_item_id in energy_item_set:
                result['reporting_period']['names'].append(energy_item_dict[energy_item_id]['name'])
                result['reporting_period']['energy_item_ids'].append(energy_item_id)
                result['reporting_period']['energy_category_names'].append(
                    energy_item_dict[energy_item_id]['energy_category_name'])
                result['reporting_period']['energy_category_ids'].append(
                    energy_item_dict[energy_item_id]['energy_category_id'])
                result['reporting_period']['units'].append(energy_item_dict[energy_item_id]['unit_of_measure'])
                result['reporting_period']['timestamps'].append(reporting[energy_item_id]['timestamps'])
                result['reporting_period']['values'].append(reporting[energy_item_id]['values'])
                result['reporting_period']['subtotals'].append(reporting[energy_item_id]['subtotal'])
                result['reporting_period']['subtotals_per_unit_area'].append(
                    reporting[energy_item_id]['subtotal'] / tenant['area'] if tenant['area'] > 0.0 else None)
                result['reporting_period']['toppeaks'].append(reporting[energy_item_id]['toppeak'])
                result['reporting_period']['onpeaks'].append(reporting[energy_item_id]['onpeak'])
                result['reporting_period']['midpeaks'].append(reporting[energy_item_id]['midpeak'])
                result['reporting_period']['offpeaks'].append(reporting[energy_item_id]['offpeak'])
                result['reporting_period']['increment_rates'].append(
                    (reporting[energy_item_id]['subtotal'] - base[energy_item_id]['subtotal']) /
                    base[energy_item_id]['subtotal']
                    if base[energy_item_id]['subtotal'] > 0.0 else None)

        result['parameters'] = {
            "names": parameters_data['names'],
            "timestamps": parameters_data['timestamps'],
            "values": parameters_data['values']
        }

        # export result to Excel file and then encode the file to base64 string
        result['excel_bytes_base64'] = excelexporters.tenantenergyitem.export(result,
                                                                              tenant['name'],
                                                                              reporting_start_datetime_local,
                                                                              reporting_end_datetime_local,
                                                                              period_type)

        resp.body = json.dumps(result)
