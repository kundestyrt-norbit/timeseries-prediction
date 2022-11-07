#!/usr/bin/env python
# coding: utf-8

import timestreamquery as timestream
import pandas as pd
import boto3
from darts import TimeSeries
from darts.utils.missing_values import fill_missing_values
import sys
import os
import darts.models.forecasting.prophet_model
from dotenv import load_dotenv
import json
from decimal import Decimal
load_dotenv()

def handler(event=None, context=None):
    #################################################
    ##### Timestream Configurations.  ###############
    #################################################
    ACCESS_KEY_ID_AWS = os.getenv("ACCESS_KEY_ID_AWS")
    SECRET_ACCESS_KEY_AWS = os.getenv("SECRET_ACCESS_KEY_AWS")
    assert ACCESS_KEY_ID_AWS
    assert SECRET_ACCESS_KEY_AWS
    ENDPOINT = "eu-west-1" # <--- specify the region service endpoint
    PROFILE = "mose-timestream" # <--- specify the AWS credentials profile
    DB_NAME = "SensorData" # <--- specify the database created in Amazon Timestream
    TABLE_NAME = "particleTest" # <--- specify the table created in Amazon Timestream
    TABLE_NAME_PREDICTION = "yrPrediction" # <--- specify the table created in Amazon Timestream


    client = timestream.createQueryClient(ENDPOINT, aws_access_key_id=ACCESS_KEY_ID_AWS, aws_secret_access_key=SECRET_ACCESS_KEY_AWS)

    #################################################
    ##### DynamoDB Configurations.  ###############
    #################################################


    ACCESS_KEY_ID_DYNAMO_DB_AWS = os.getenv("ACCESS_KEY_ID_DYNAMO_DB_AWS")
    SECRET_ACCESS_KEY_DYNAMO_DB_AWS = os.getenv("SECRET_ACCESS_KEY_DYNAMO_DB_AWS")
    DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE")
    assert ACCESS_KEY_ID_DYNAMO_DB_AWS
    assert SECRET_ACCESS_KEY_DYNAMO_DB_AWS
    assert DYNAMODB_TABLE

    dynamodb = boto3.resource('dynamodb',
        region_name='eu-north-1',
        aws_access_key_id=ACCESS_KEY_ID_DYNAMO_DB_AWS,
        aws_secret_access_key=SECRET_ACCESS_KEY_DYNAMO_DB_AWS,
    )
    prediction_table = dynamodb.Table(DYNAMODB_TABLE)

    query_describe = """
    DESCRIBE {}.{}
    """.format(DB_NAME, TABLE_NAME)

    describe_table = timestream.executeQueryAndReturnAsDataframe(client, query_describe, True)

    sensors = describe_table[describe_table["Timestream attribute type"] == "MULTI"]["Column"]
    columns_to_extract = ", ".join([f"ROUND(AVG({sensor_name}), 2) as {sensor_name}_" for sensor_name in sensors])


    query_get_all_data = f"""
    SELECT BIN(time, 1h) as time_, {columns_to_extract}
    FROM {DB_NAME}.{TABLE_NAME}
    WHERE gateway_id='8'
    GROUP BY BIN(time, 1h)
    ORDER BY BIN(time, 1h)
    """

    df = timestream.executeQueryAndReturnAsDataframe(client, query_get_all_data, True)


    query_describe_prediction = """
    DESCRIBE {}.{}
    """.format(DB_NAME, TABLE_NAME_PREDICTION)

    describe_table_prediction = timestream.executeQueryAndReturnAsDataframe(client, query_describe_prediction, True)

    yr_prediction_columns = describe_table_prediction[describe_table_prediction["Timestream attribute type"] == "MULTI"]["Column"]
    columns_to_extract_prediction = ", ".join([f'ROUND(AVG("{column}"), 2) as "{column}_"' for column in yr_prediction_columns])
    query_get_all_data_prediction = f"""
    SELECT BIN(time, 1h) as time_, {columns_to_extract_prediction}
    FROM {DB_NAME}.{TABLE_NAME_PREDICTION}
    GROUP BY BIN(time, 1h)
    ORDER BY BIN(time, 1h)
    """

    df_prediction = timestream.executeQueryAndReturnAsDataframe(client, query_get_all_data_prediction, True)

    df.index = pd.to_datetime(df.time_)
    df.index = df.index.tz_localize(None)
    series = fill_missing_values(
        TimeSeries.from_dataframe(df, value_cols=[sensor_name + "_" for sensor_name in sensors], fill_missing_dates=True))
    df_prediction.index = pd.to_datetime(df_prediction.time_)
    df_prediction.index = df_prediction.index.tz_localize(None)
    df_prediction_renamed = df_prediction.rename(columns={
        '1h_air_temperature_': 'air_temperature_', 
        '1h_percipitation_': 'percipitation_',
        '1h_wind_speed_': 'wind_speed_',
        '1h_wind_direction_cos_': 'wind_direction_cos_',
        '1h_wind_direction_sin_': 'wind_direction_sin_'
    })
    series_prediction = fill_missing_values(
        TimeSeries.from_dataframe(df_prediction_renamed, value_cols=[
            'air_temperature_', 
            'percipitation_', 
            'wind_speed_',
            'wind_direction_cos_',
            'wind_direction_sin_'
            ], fill_missing_dates=True)
    )
    series_prediction = series_prediction.shift(1)


    last_value = df_prediction.iloc[-1]
    columns = list(set([col.split('h_')[1] for col in last_value.index if 'h_' in col ]))
    predicted_forecast = pd.DataFrame([[last_value[f'{i}h_{column}'] for column in columns] for i in range(1,25)], columns=columns,
                    index=[pd.to_datetime(last_value['time_']) + pd.DateOffset(hours=i) for i in range(24)])
    predicted_forecast.index.name = 'time_'
    series_prediction_test = fill_missing_values(
        TimeSeries.from_dataframe(predicted_forecast, value_cols=[
            'air_temperature_', 
            'percipitation_', 
            'wind_speed_',
            'wind_direction_cos_',
            'wind_direction_sin_'
            ], fill_missing_dates=True)
    ).shift(1)  



    prophet = darts.models.forecasting.prophet_model.Prophet()
    model_output = []
    for sensor_name in sensors:
        sensor_name_ = sensor_name + "_"
        prophet.fit(
            series[sensor_name_], 
            future_covariates=series_prediction[:-1],
        )
        prediction_prophet = prophet.predict(n=24, 
                                        future_covariates=series_prediction[:-1].concatenate(series_prediction_test),
                                                num_samples=1000,
                                        )
        model_output.append((sensor_name, 
                            {
                                'percentile095': prediction_prophet.quantile(0.95),
                                'percentile050': prediction_prophet.quantile(0.50),
                                'percentile005': prediction_prophet.quantile(0.05)
                            }
                            ))
        
    item_to_put = {}
    for sensor in model_output:
        item_to_put[sensor[0]] = {
            'percentile005': list(sensor[1]['percentile005'].values().flatten()),
            'percentile050': list(sensor[1]['percentile050'].values().flatten()),
            'percentile095': list(sensor[1]['percentile095'].values().flatten()),
            }
    item_to_put['gatewayId'] = 8
    item_to_put['time'] = df.time_[len(df.time_)-1]
    item = json.loads(json.dumps(item_to_put), parse_float=Decimal)
    prediction_table.put_item(Item=item)


if __name__ == '__main__':
    handler()