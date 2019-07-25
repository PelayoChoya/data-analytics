#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
calculate cgm statsistics for a single tidepool (donor) dataset
'''


# %% REQUIRED LIBRARIES
import os
import sys
import hashlib
import pytz
import numpy as np
import pandas as pd
import datetime as dt


# TODO: figure out how to get rid of these path dependcies
get_donor_data_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
if get_donor_data_path not in sys.path:
    sys.path.insert(0, get_donor_data_path)
import environmentalVariables
from get_donor_data.get_single_donor_metadata import get_shared_metadata
from get_donor_data.get_single_tidepool_dataset import get_data

# %% CONSTANTS
MGDL_PER_MMOLL = 18.01559


# %% FUNCTIONS
'''
the functions that are called in this script,
which includes notes of where the functions came from,
and whether they were refactored
'''


def hash_userid(userid, salt):
    '''
    taken from anonymize-and-export.py
    refactored name(s) to meet style guide
    '''
    usr_string = userid + salt
    hash_user = hashlib.sha256(usr_string.encode())
    hashid = hash_user.hexdigest()

    return hashid


def get_type(val):
    return type(val).__name__


def remove_negative_durations(df):
    '''
    taken from https://github.com/tidepool-org/data-analytics/blob/
    etn/get-settings-and-events/projects/get-donors-pump-settings/
    get-users-settings-and-events.py

    refactored name(s) to meet style guide
    refactored pandas field call to df["field"] instead of df.field
    refactored because physical activity includes embedded json, whereas
    the other fields in the data model require a integer
    '''
    if "duration" in list(df):
        type_ = df["duration"].apply(get_type)
        valid_index = ((type_ == "int") & (df["duration"].notnull()))
        n_negative_durations = sum(df.loc[valid_index, "duration"] < 0)
        if n_negative_durations > 0:
            df = df[~(df.loc[valid_index, "duration"] < 0)]
    else:
        n_negative_durations = np.nan

    return df, n_negative_durations


def expand_embedded_dict(df, field, key_):
    '''
    this is new, should be refactored for speed as the current process
    creates a dataframe of all of keys instead of just the key of interest
    '''
    if field in list(df):
        notnull_idx = df[field].notnull()
        temp_df = pd.DataFrame(df.loc[notnull_idx, field].tolist())  # TODO: this can be sped up by only getting the field key of interest
        if key_ in list(temp_df):
            df[field + "." + key_] = temp_df[key_]
    return df


def tslim_calibration_fix(df):
    '''
    taken from https://github.com/tidepool-org/data-analytics/blob/
    etn/get-settings-and-events/projects/get-donors-pump-settings/
    get-users-settings-and-events.py

    refactored name(s) to meet style guide
    refactored pandas field call to df["field"] instead of df.field
    refactored to only expand one field
    '''

    # expand payload field one level
    df = expand_embedded_dict(df, "payload", "calibration_reading")

    if "payload.calibration_reading" in list(df):

        search_for = ['tan']
        tandem_data_index = (
            (df["deviceId"].str.contains('|'.join(search_for)))
            & (df["type"] == "deviceEvent")
        )

        cal_index = df["payload.calibration_reading"].notnull()
        valid_index = tandem_data_index & cal_index

        n_cal_readings = sum(valid_index)

        if n_cal_readings > 0:
            # if reading is > 30 then it is in the wrong units
            if df["payload.calibration_reading"].min() > 30:
                df.loc[cal_index, "value"] = (
                    df.loc[valid_index, "payload.calibration_reading"]
                    / MGDL_PER_MMOLL
                )
            else:
                df.loc[cal_index, "value"] = (
                    df.loc[valid_index, "payload.calibration_reading"]
                )
    else:
        n_cal_readings = 0
    return df, n_cal_readings


def get_and_fill_timezone(df):
    '''
    this is new to deal with healthkit data
    requires that a data frame that contains payload and HKTimeZone is passed
    '''
    df = expand_embedded_dict(df, "payload", "HKTimeZone")
    if "timezone" not in list(df):
        if "payload.HKTimeZone" in list(df):
            df.rename(columns={"payload.HKTimeZone": "timezone"}, inplace=True)
        else:
            df["timezone"] = np.nan
    else:
        if "payload.HKTimeZone" in list(df):
            hk_tz_idx = df["payload.HKTimeZone"].notnull()
            df.loc[hk_tz_idx, "timezone"] = (
                df.loc[hk_tz_idx, "payload.HKTimeZone"]
            )

    df["timezone"].fillna(method='ffill', inplace=True)
    df["timezone"].fillna(method='bfill', inplace=True)

    return df["timezone"]


def make_tz_unaware(date_time):
    return date_time.replace(tzinfo=None)


def to_utc_datetime(df):
    '''
    this is new to deal with perfomance issue with the previous method
    of converting to string to datetime with pd.to_datetime()
    '''
    utc_time_tz_aware = pd.to_datetime(
        df["time"],
        format="%Y-%m-%dT%H:%M:%S",
        utc=True
    )
    utc_tz_unaware = utc_time_tz_aware.apply(make_tz_unaware)

    return utc_tz_unaware


def get_timezone_offset(currentDate, currentTimezone):

    # edge case for 'US/Pacific-New'
    if currentTimezone == 'US/Pacific-New':
        currentTimezone = 'US/Pacific'

    tz = pytz.timezone(currentTimezone)

    tzoNum = int(
        tz.localize(currentDate + dt.timedelta(days=1)).strftime("%z")
    )
    tzoHours = np.floor(tzoNum / 100)
    tzoMinutes = round((tzoNum / 100 - tzoHours) * 100, 0)
    tzoSign = np.sign(tzoHours)
    tzo = int((tzoHours * 60) + (tzoMinutes * tzoSign))

    return tzo


def get_local_time(df):

    tzo = df[['utcTime', 'inferredTimezone']].apply(
        lambda x: get_timezone_offset(*x), axis=1
    )
    local_time = df['utcTime'] + pd.to_timedelta(tzo, unit="m")

    return local_time


# %% GET DATA FROM API
'''
get metadata and data for a donor that has shared with bigdata
NOTE: functions assume you have an .env with bigdata account credentials
'''

userid = "0d4524bc11"
donor_group = "bigdata"

metadata, _ = get_shared_metadata(
    donor_group=donor_group,
    userid_of_shared_user=userid  # TODO: this should be refactored in several places to be userid
)
data, _ = get_data(
    donor_group=donor_group,
    userid=userid,
    weeks_of_data=4
    )


# %% CREATE META DATAFRAME (metadata)
metadata = pd.DataFrame(index=[userid])


# %% HASH USER ID
hashid = hash_userid(userid, os.environ['BIGDATA_SALT'])
data["userid"] = userid
data["hashid"] = hashid


# %% CLEAN DATA
data_fields = list(data)
# remove negative durations
if "duration" in data_fields:
    data["duration"], n_negative_durations = (
        remove_negative_durations(data[["duration"]].copy())
    )
else:
    n_negative_durations = np.nan
metadata["nNegativeDurations"] = n_negative_durations

# Tslim calibration bug fix
data, n_cal_readings = tslim_calibration_fix(data)
metadata["nTandemAndPayloadCalReadings"] = n_cal_readings


# %% TIME RELATED ITEMS
data["utcTime"] = to_utc_datetime(data[["time"]].copy())
if "timezone" not in list(data):
    data["timezone"] = np.nan
data["inferredTimezone"] = get_and_fill_timezone(
    data[["timezone", "payload"]].copy()
)
# estimate local time (simple method)
# TODO: this really needs to be sped up
data["localTime"] = get_local_time(
    data[['utcTime', 'inferredTimezone']].copy()
)





#data["day"] = pd.DatetimeIndex(data["localTime"]).date
#
## round to the nearest 5 minutes
## TODO: once roundTime is pushed to tidals repository then this line can be replaced
## with td.clean.round_time
#data = round_time(data, timeIntervalMinutes=5, timeField="time",
#                  roundedTimeFieldName="roundedTime", startWithFirstRecord=True,
#                  verbose=False)
#
#data["roundedLocalTime"] = data["roundedTime"] + pd.to_timedelta(data["tzo"], unit="m")
#data.sort_values("uploadTime", ascending=False, inplace=True)
#
## AGE, & YLW
#data["age"] = np.floor((data["localTime"] - bDate).dt.days/365.25).astype(int)
#data["ylw"] = np.floor((data["localTime"] - dDate).dt.days/365.25).astype(int)


# %% CGM DATA

#def removeInvalidCgmValues(df):
#
#    nBefore = len(df)
#    # remove values < 38 and > 402 mg/dL
#    df = df.drop(df[((df.type == "cbg") &
#                     (df.value < 2.109284236597303))].index)
#    df = df.drop(df[((df.type == "cbg") &
#                     (df.value > 22.314006924003046))].index)
#    nRemoved = nBefore - len(df)
#
#    return df, nRemoved

# get rid of cgm values too low/high (< 38 & > 402 mg/dL)
#data, nInvalidCgmValues = removeInvalidCgmValues(data)
#metadata["nInvalidCgmValues"] = nInvalidCgmValues
