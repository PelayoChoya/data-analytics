#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
description: get users settings and events
version: 0.0.1
created: 2019-01-11
author: Ed Nykaza
dependencies:
    *
license: BSD-2-Clause
"""


# %% REQUIRED LIBRARIES
import pandas as pd
import numpy as np
import tidals as td
import os
import pdb


# %% USER INPUTS (ADD THIS IN LATER)
#codeDescription = "Get user's settings and events"
#parser = argparse.ArgumentParser(description=codeDescription)


# %% FUNCTIONS

# CLEAN DATA FUNCTIONS
def removeNegativeDurations(df):
    if "duration" in list(df):
        nNegativeDurations = sum(df.duration < 0)
        if nNegativeDurations > 0:
            df = df[~(df.duration < 0)]
    else:
        nNegativeDurations = np.nan

    return df, nNegativeDurations


def removeInvalidCgmValues(df):

    nBefore = len(df)
    # remove values < 38 and > 402 mg/dL
    df = df.drop(df[((df.type == "cbg") &
                     (df.value < 2.109284236597303))].index)
    df = df.drop(df[((df.type == "cbg") &
                     (df.value > 22.314006924003046))].index)
    nRemoved = nBefore - len(df)

    return df, nRemoved


def tslimCalibrationFix(df):
    searchfor = ['tan']
    tandemDataIndex = ((df.deviceId.str.contains('|'.join(searchfor))) &
                       (df.type == "deviceEvent"))

    if "payload.calibration_reading" in list(df):
        payloadCalReadingIndex = df["payload.calibration_reading"].notnull()

        nTandemAndPayloadCalReadings = sum(tandemDataIndex &
                                           payloadCalReadingIndex)

        if nTandemAndPayloadCalReadings > 0:
            # if reading is > 30 then it is in the wrong units
            if df["payload.calibration_reading"].min() > 30:
                df.loc[payloadCalReadingIndex, "value"] = \
                    df[tandemDataIndex & payloadCalReadingIndex] \
                    ["payload.calibration_reading"] / 18.01559
            else:
                df.loc[payloadCalReadingIndex, "value"] = \
                    df[tandemDataIndex &
                        payloadCalReadingIndex]["payload.calibration_reading"]
    else:
        nTandemAndPayloadCalReadings = 0
    return df, nTandemAndPayloadCalReadings


# OTHER
def tempRemoveFields(df):
    removeFields = ["suppressed",
                    "recommended",
                    "payload"]

    tempRemoveFields = list(set(df) & set(removeFields))
    tempDf = df[tempRemoveFields]
    df = df.drop(columns=tempRemoveFields)

    return df, tempDf


def flattenJson(df):

    # remove fields that we don't want to flatten
    df, holdData = tempRemoveFields(df)

    # get a list of data types of column headings
    columnHeadings = list(df)

    # loop through each columnHeading
    newDataFrame = pd.DataFrame()

    for colHead in columnHeadings:
        if any(isinstance(item, list) for item in df[colHead]):
            listBlob = df[colHead][df[colHead].astype(str).str[0] == "["]
            df.loc[listBlob.index, colHead] = df.loc[listBlob.index, colHead].str[0]

        # if the df field has embedded json
        if any(isinstance(item, dict) for item in df[colHead]):
            # grab the data that is in brackets
            jsonBlob = df[colHead][df[colHead].astype(str).str[0] == "{"]

            # replace those values with nan
            df.loc[jsonBlob.index, colHead] = np.nan

            # turn jsonBlob to dataframe
            newDataFrame = pd.concat([newDataFrame, pd.DataFrame(jsonBlob.tolist(),
                                     index=jsonBlob.index).add_prefix(colHead + '.')], axis=1)

    df = pd.concat([df, newDataFrame, holdData], axis=1)

    df.sort_index(axis=1, inplace=True)

    return df


def mergeWizardWithBolus(df):

    if "wizard" in df["type"].unique():
        bolusData = df[df.type == "bolus"].copy().dropna(axis=1, how="all")
        wizardData = df[df.type == "wizard"].copy().dropna(axis=1, how="all")

        # merge the wizard data with the bolus data
        wizardData["calculatorId"] = wizardData["id"]
        wizardDataFields = [
            "bgInput",
            "bgTarget.high",
            "bgTarget.low",
            "bgTarget.range",
            "bgTarget.target",
            "bolus",
            "carbInput",
            "calculatorId",
            "insulinCarbRatio",
            "insulinOnBoard",
            "insulinSensitivity",
            "recommended.carb",
            "recommended.correction",
            "recommended.net",
            "units",
        ]
        keepTheseWizardFields = \
            set(wizardDataFields).intersection(list(wizardData))
        bolusData = pd.merge(bolusData,
                             wizardData[list(keepTheseWizardFields)],
                             how="left",
                             left_on="id",
                             right_on="bolus")

        mergedBolusData = bolusData.drop("bolus", axis=1)
    else:
        mergedBolusData = pd.DataFrame()

    return mergedBolusData


def addUploadDate(df):
    uploadTimes = pd.DataFrame(df[df.type == "upload"].groupby("uploadId").time.describe()["top"])
    uploadTimes.reset_index(inplace=True)
    uploadTimes.rename(columns={"top": "uploadTime"}, inplace=True)
    df = pd.merge(df, uploadTimes, how='left', on='uploadId')
    df["uploadTime"] = pd.to_datetime(df["uploadTime"])

    return df


def mmolL_to_mgdL(mmolL):
    return mmolL * 18.01559


def round_time(df, timeIntervalMinutes=5, timeField="time",
               roundedTimeFieldName="roundedTime", startWithFirstRecord=True,
               verbose=False):
    '''
    A general purpose round time function that rounds the "time"
    field to nearest <timeIntervalMinutes> minutes
    INPUTS:
        * a dataframe (df) that contains a time field that you want to round
        * timeIntervalMinutes (defaults to 5 minutes given that most cgms output every 5 minutes)
        * timeField to round (defaults to the UTC time "time" field)
        * roundedTimeFieldName is a user specified column name (defaults to roundedTime)
        * startWithFirstRecord starts the rounding with the first record if True, and the last record if False (defaults to True)
        * verbose specifies whether the extra columns used to make calculations are returned
    '''

    df.sort_values(by=timeField, ascending=startWithFirstRecord, inplace=True)
    df.reset_index(drop=True, inplace=True)

    # make sure the time field is in the right form
    t = pd.to_datetime(df[timeField])

    # calculate the time between consecutive records
    t_shift = pd.to_datetime(df[timeField].shift(1))
    df["timeBetweenRecords"] = \
        round((t - t_shift).dt.days*(86400/(60 * timeIntervalMinutes)) +
              (t - t_shift).dt.seconds/(60 * timeIntervalMinutes)) * timeIntervalMinutes

    # separate the data into chunks if timeBetweenRecords is greater than
    # 2 times the <timeIntervalMinutes> minutes so the rounding process starts over
    largeGaps = list(df.query("abs(timeBetweenRecords) > " + str(timeIntervalMinutes * 2)).index)
    largeGaps.insert(0, 0)
    largeGaps.append(len(df))

    for gIndex in range(0, len(largeGaps) - 1):
        chunk = t[largeGaps[gIndex]:largeGaps[gIndex+1]]
        firstRecordChunk = t[largeGaps[gIndex]]

        # calculate the time difference between each time record and the first record
        df.loc[largeGaps[gIndex]:largeGaps[gIndex+1], "minutesFromFirstRecord"] = \
            (chunk - firstRecordChunk).dt.days*(86400/(60)) + (chunk - firstRecordChunk).dt.seconds/(60)

        # then round to the nearest X Minutes
        # NOTE: the ".000001" ensures that mulitples of 2:30 always rounds up.
        df.loc[largeGaps[gIndex]:largeGaps[gIndex+1], "roundedMinutesFromFirstRecord"] = \
            round((df.loc[largeGaps[gIndex]:largeGaps[gIndex+1],
                          "minutesFromFirstRecord"] / timeIntervalMinutes) + 0.000001) * (timeIntervalMinutes)

        roundedFirstRecord = (firstRecordChunk + pd.Timedelta("1microseconds")).round(str(timeIntervalMinutes) + "min")
        df.loc[largeGaps[gIndex]:largeGaps[gIndex+1], roundedTimeFieldName] = \
            roundedFirstRecord + \
            pd.to_timedelta(df.loc[largeGaps[gIndex]:largeGaps[gIndex+1],
                                   "roundedMinutesFromFirstRecord"], unit="m")

    # sort by time and drop fieldsfields
    df.sort_values(by=timeField, ascending=startWithFirstRecord, inplace=True)
    df.reset_index(drop=True, inplace=True)
    if verbose is False:
        df.drop(columns=["timeBetweenRecords",
                         "minutesFromFirstRecord",
                         "roundedMinutesFromFirstRecord"], inplace=True)

    return df


def get_descriptive_stats(df, newName, dataSubType):

    newDf = df[dataSubType].describe().add_suffix(newName)

    newDf[("rangeOf" + newName)] = \
        newDf[("max" + newName)] - \
        newDf[("min" + newName)]

    return newDf


def get_bolusDaySummary(bolusData):

    if "extended" not in bolusData:
        bolusData["extended"] = 0

    bolusByDay = bolusData.groupby(bolusData["day"])

    # total bolus insulin for each day
    bolusDaySummary = pd.DataFrame(bolusByDay.normal.sum())
    bolusDaySummary = bolusDaySummary.rename(columns={"normal":"totalAmountOfNormalBolusInsulin"})

    bolusDaySummary["totalAmountOfExtendedBolusInsulin"] = bolusByDay.extended.sum().fillna(0.0)
    bolusDaySummary["totalAmountOfBolusInsulin"] = bolusDaySummary["totalAmountOfNormalBolusInsulin"].fillna(0.0) + \
                                           bolusDaySummary["totalAmountOfExtendedBolusInsulin"].fillna(0.0)

    # bolus range for normal boluses
    normalBasalDF = get_descriptive_stats(bolusByDay, "NormalBolusAmountPerBolus", "normal")
    bolusDaySummary = pd.concat([bolusDaySummary, normalBasalDF], axis = 1)

    # total number of bolus types per day
    bolusTypePerDay = bolusData.groupby(["day",
                                         "subType"]).size().unstack()

    bolusDaySummary["numberOfNormalBoluses"] = bolusTypePerDay["normal"].fillna(0)

    if "square" not in list(bolusTypePerDay):
        bolusDaySummary["numberOfSquareBoluses"] = 0
    else:
        bolusDaySummary["numberOfSquareBoluses"] = bolusTypePerDay["square"].fillna(0)

    if "dual/square" not in list(bolusTypePerDay):
        bolusDaySummary["numberOfDualBoluses"] = 0
    else:
        bolusDaySummary["numberOfDualBoluses"] = bolusTypePerDay["dual/square"].fillna(0)

    bolusDaySummary["numberOfAllBolusTypes"] = bolusDaySummary["numberOfNormalBoluses"] + \
                                        bolusDaySummary["numberOfSquareBoluses"] + \
                                        bolusDaySummary["numberOfDualBoluses"]

    return bolusDaySummary


def get_basalDaySummary(basal):
    # group data by day
    basalByDay = basal.groupby(basal["day"])

    # total basal insulin per day
    basalDaySummary = pd.DataFrame(basalByDay.totalAmountOfBasalInsulin.sum())

    # total number of basals types per day
    basalTypePerDay = basal.groupby(["day", "deliveryType"]).size().unstack()

    basalDaySummary["numberOfScheduledBasals"] = basalTypePerDay["scheduled"].fillna(0)
    if "suspend" not in list(basalTypePerDay):
        basalDaySummary["numberOfSuspendedBasals"] = 0
    else:
        basalDaySummary["numberOfSuspendedBasals"] = basalTypePerDay["suspend"].fillna(0)
    if "temp" not in list(basalTypePerDay):
        basalDaySummary["numberOfTempBasals"] = 0
    else:
        basalDaySummary["numberOfTempBasals"] = basalTypePerDay["temp"].fillna(0)

    basalDaySummary["totalNumberOfBasals"] = basalDaySummary["numberOfScheduledBasals"] + \
                                 basalDaySummary["numberOfTempBasals"]

    return basalDaySummary


# %% LOAD IN ONE FILE, BUT EVENTUALLY THIS WILL LOOOP THROUGH ALL USER'S
dataPulledDate = "2018-09-28"
phiDate = "PHI-" + dataPulledDate
donorPath = os.path.join("..", "bigdata-processing-pipeline", "data", phiDate + "-donor-data")

donorList = phiDate + "-uniqueDonorList.csv"
donors = td.load.load_csv(os.path.join(donorPath, donorList))

# this is where the loop will go:
for dIndex in range(0, len(donors)):

    # %% ID, HASHID, AGE, & YLW
    userID = donors.userID[dIndex]
    hashID = donors.hashID[dIndex]
    # round all birthdays and diagnosis dates to the first day of the month (to protect identities)
    bDate = pd.to_datetime(donors.bDay[dIndex][0:7])
    dDate = pd.to_datetime(donors.dDay[dIndex][0:7])


    # %% LOAD IN DONOR JSON DATA
    metadata = pd.DataFrame(index=[dIndex])
    jsonDataPath = os.path.join(donorPath, phiDate + "-donorJsonData")
    jsonFileName = os.path.join(jsonDataPath, "PHI-" + userID + ".json")

    if os.path.exists(jsonFileName):
        fileSize = os.stat(jsonFileName).st_size
        metadata["fileSizeKB"] = fileSize / 1000
        if fileSize > 1000:
            data = td.load.load_json(jsonFileName)

            # sort the data by time
            data.sort_values("time", inplace=True)

            # flatten the embedded json
            data = flattenJson(data)


            # %% CLEAN DATA
            # remove negative durations
            data, nNegativeDurations = removeNegativeDurations(data)
            metadata["nNegativeDurations"] = nNegativeDurations

            # get rid of cgm values too low/high (< 38 & > 402 mg/dL)
            data, nInvalidCgmValues = removeInvalidCgmValues(data)
            metadata["nInvalidCgmValues"] = nInvalidCgmValues

            # Tslim calibration bug fix
            data, nTandemAndPayloadCalReadings = tslimCalibrationFix(data)
            metadata["nTandemAndPayloadCalReadings"] = nTandemAndPayloadCalReadings


            # %% ADD UPLOAD DATE
            # attach upload time to each record, for resolving duplicates
            if "upload" in data.type.unique():
                data = addUploadDate(data)


                # %% TIME (UTC, TIMEZONE, DAY AND EVENTUALLY LOCAL TIME)
                data["utcTime"] = pd.to_datetime(data["time"])
                data["timezone"].fillna(method='ffill', inplace=True)
                data["timezone"].fillna(method='bfill', inplace=True)
                data["day"] = pd.DatetimeIndex(data["utcTime"]).date

                # round to the nearest 5 minutes
                # TODO: once roundTime is pushed to tidals repository then this line can be replaced
                # with td.clean.round_time
                data = round_time(data, timeIntervalMinutes=5, timeField="time",
                                  roundedTimeFieldName="roundedTime", startWithFirstRecord=True,
                                  verbose=False)
                data.sort_values("uploadTime", ascending=False, inplace=True)


                # %% ID, HASHID, AGE, & YLW
                data["userID"] = userID
                data["hashID"] = hashID
                data["age"] = np.floor((data["utcTime"] - bDate).dt.days/365.25).astype(int)
                data["ylw"] = np.floor((data["utcTime"] - dDate).dt.days/365.25).astype(int)

                commonColumnHeadings = ["hashID",
                                        "age",
                                        "ylw"]


                # %% BOLUS EVENTS (CORRECTION, AND MEAL INCLUING: CARBS, EXTENDED, DUAL)
                bolus = mergeWizardWithBolus(data)
                if len(bolus) > 0:
                    # get rid of duplicates that have the same ["time", "normal"]
                    bolus.sort_values("uploadTime", ascending=False, inplace=True)
                    bolus, nBolusDuplicatesRemoved = \
                        td.clean.remove_duplicates(bolus, bolus[["deviceTime", "normal"]])
                    metadata["nBolusDuplicatesRemoved"] = nBolusDuplicatesRemoved

                    # get a summary of boluses per day
                    bolusDaySummary = get_bolusDaySummary(bolus)

                    if "extended" not in bolus:
                        bolus["extended"] = np.nan
                        bolus["duration"] = np.nan

                    # cir associated with bolus event
                    if "insulinSensitivities" in list(bolus):
                        pdb.set_trace()
                    if "carbRatios" in list(bolus):
                        pdb.set_trace()

                    bolus["isf_mmolL_U"] = bolus["insulinSensitivity"]
                    bolus["isf"] = mmolL_to_mgdL(bolus["isf_mmolL_U"])

                    bolusCH = commonColumnHeadings.copy()
                    bolusCH.extend(["utcTime", "roundedTime", "normal", "carbInput", "subType",
                                    "insulinOnBoard", "bgInput",
                                    "isf", "isf_mmolL_U", "insulinCarbRatio"])
                    bolusEvents = bolus.loc[bolus["normal"].notnull(), bolusCH]
                    bolusEvents.loc[bolusEvents["bgInput"] == 0, "bgInput"] = np.nan
                    bolusEvents = bolusEvents.rename(columns={"normal": "unitsInsulin",
                                                              "bgInput": "bg_mmolL"})
                    bolusEvents["bg_mgdL"] = mmolL_to_mgdL(bolusEvents["bg_mmolL"])
                    bolusEvents["eventType"] = "correction"
                    bolusEvents.loc[bolusEvents["carbInput"] == 0, "eventType"] = "meal"


                    # %% PUMP SETTINGS
                    if "pumpSettings" in data.type.unique():
                        pumpSettings = data[data.type == "pumpSettings"].copy().dropna(axis=1, how="all")
                        pumpSettings.sort_values("uploadTime", ascending=False, inplace=True)

                        pumpSettings, nPumpSettingsDuplicatesRemoved = \
                        td.clean.remove_duplicates(pumpSettings, pumpSettings[["deviceTime"]])
                        metadata["nPumpSettingsDuplicatesRemoved"] = nPumpSettingsDuplicatesRemoved

                        # ISF
                        isfCH = commonColumnHeadings.copy()
                        isfCH.extend(["isfTime", "isf", "isf_mmolL_U"])

                        if "insulinSensitivity.amount" in list(pumpSettings):
                            isfColHead = "insulinSensitivity"
                            pumpSettings["isf_mmolL_U"] = pumpSettings[isfColHead + ".amount"]
                            pumpSettings["isf"] = mmolL_to_mgdL(pumpSettings["isf_mmolL_U"])
                            pumpSettings["isfTime"] = pd.to_datetime(pumpSettings["day"]) + \
                                pd.to_timedelta(pumpSettings[isfColHead + ".start"], unit="ms")

                            isf = pumpSettings.loc[pumpSettings["isf"].notnull(), isfCH]
                        else:
                            isfColHead = "insulinSensitivities"
                            isf = pd.DataFrame(columns=isfCH)
                            for p, actSched in zip(pumpSettings.index, pumpSettings["activeSchedule"]):
                                tempDF = pd.DataFrame(pumpSettings.loc[p, isfColHead + "." + actSched])
                                tempDF["day"] = pumpSettings.loc[p, "day"]
                                tempDF["isfTime"] = pd.to_datetime(tempDF["day"]) + pd.to_timedelta(tempDF["start"], unit="ms")
                                tempDF["hashID"] = pumpSettings.loc[p, "hashID"]
                                tempDF["age"] = pumpSettings.loc[p, "age"]
                                tempDF["ylw"] = pumpSettings.loc[p, "ylw"]
                                tempDF["isf_mmolL_U"] = tempDF["amount"]
                                tempDF["isf"] = mmolL_to_mgdL(tempDF["isf_mmolL_U"])
                                isf = pd.concat([isf, tempDF[isfCH]], ignore_index=True)



                        # CIR
                        cirCH = commonColumnHeadings.copy()
                        cirCH.extend(["cirTime", "cir"])

                        if "carbRatio.amount" in list(pumpSettings):
                            cirColHead = "carbRatio"
                            pumpSettings["cir"] = pumpSettings[cirColHead + ".amount"]
                            pumpSettings["cirTime"] = pd.to_datetime(pumpSettings["day"]) + \
                                pd.to_timedelta(pumpSettings[cirColHead + ".start"], unit="ms")

                            cir = pumpSettings.loc[pumpSettings["cir"].notnull(), cirCH]
                        else:
                            cirColHead = "carbRatios"
                            cir = pd.DataFrame(columns=cirCH)
                            for p, actSched in zip(pumpSettings.index, pumpSettings["activeSchedule"]):
                                tempDF = pd.DataFrame(pumpSettings.loc[p, cirColHead + "." + actSched])
                                tempDF["day"] = pumpSettings.loc[p, "day"]
                                tempDF["cirTime"] = pd.to_datetime(tempDF["day"]) + pd.to_timedelta(tempDF["start"], unit="ms")
                                tempDF["hashID"] = pumpSettings.loc[p, "hashID"]
                                tempDF["age"] = pumpSettings.loc[p, "age"]
                                tempDF["ylw"] = pumpSettings.loc[p, "ylw"]
                                tempDF["cir"] = tempDF["amount"].astype(float)
                                cir = pd.concat([cir, tempDF[cirCH]], ignore_index=True)


                        # CORRECTION TARGET
                        ctCH = commonColumnHeadings.copy()
                        ctCH.extend(["ctTime", "correctionTargetLow", "correctionTargetHigh",
                                     "correctionTarget", "correctionTargetRange"])
                        if "bgTarget.start" in list(pumpSettings):
                            bgTargetColHead = "bgTarget"

                            # low
                            if bgTargetColHead + ".low" in list(pumpSettings):
                                pumpSettings["correctionTargetLow_mmolL"] = pumpSettings[bgTargetColHead + ".low"]
                                pumpSettings["correctionTargetLow"] = \
                                    mmolL_to_mgdL(pumpSettings["correctionTargetLow_mmolL"])
                            else:
                                pumpSettings["correctionTargetLow_mmolL"] = np.nan
                                pumpSettings["correctionTargetLow"] = np.nan

                            # high
                            if bgTargetColHead + ".high" in list(pumpSettings):
                                pumpSettings["correctionTargetHigh_mmolL"] = pumpSettings[bgTargetColHead + ".high"]
                                pumpSettings["correctionTargetHigh"] = \
                                    mmolL_to_mgdL(pumpSettings["correctionTargetHigh_mmolL"])

                            else:
                                pumpSettings["correctionTargetHigh_mmolL"] = np.nan
                                pumpSettings["correctionTargetHigh"] = np.nan

                            # target
                            if bgTargetColHead + ".target" in list(pumpSettings):
                                pumpSettings["correctionTarget_mmolL"] = pumpSettings[bgTargetColHead + ".target"]
                                pumpSettings["correctionTarget"] = \
                                    mmolL_to_mgdL(pumpSettings["correctionTarget_mmolL"])

                            else:
                                pumpSettings["correctionTarget_mmolL"] = np.nan
                                pumpSettings["correctionTarget"] = np.nan

                            # range
                            if bgTargetColHead + ".range" in list(pumpSettings):
                                pumpSettings["correctionTargetRange_mmolL"] = pumpSettings[bgTargetColHead + ".range"]
                                pumpSettings["correctionTargetRange"] = \
                                    mmolL_to_mgdL(pumpSettings["correctionTargetRange_mmolL"])

                            else:
                                pumpSettings["correctionTargetRange_mmolL"] = np.nan
                                pumpSettings["correctionTargetRange"] =np.nan

                            pumpSettings["ctTime"] = pd.to_datetime(pumpSettings["day"]) + \
                                pd.to_timedelta(pumpSettings[bgTargetColHead + ".start"], unit="ms")


                            correctionTarget = pumpSettings.loc[pumpSettings["ctTime"].notnull(), ctCH]

                        else:
                            bgTargetColHead = "bgTargets"
                            pdb.set_trace()



                        # SCHEDULED BASAL RATES
                        sbrCH = commonColumnHeadings.copy()
                        sbrCH.extend(["sbrTime", "rate", "type"])
                        sbr = pd.DataFrame(columns=sbrCH)
                        for p, actSched in zip(pumpSettings.index, pumpSettings["activeSchedule"]):
                            if 'Auto Mode' not in actSched:
                                tempDF = pd.DataFrame(pumpSettings.loc[p, "basalSchedules." + actSched])
                                tempDF["day"] = pumpSettings.loc[p, "day"]
                                tempDF["type"] = np.nan
                                tempDF["sbrTime"] = pd.to_datetime(tempDF["day"]) + pd.to_timedelta(tempDF["start"], unit="ms")
                            else:
                                tempDF = pd.DataFrame(index=[0])
                                tempDF["sbrTime"] = np.nan
                                tempDF["rate"] = np.nan
                                tempDF["type"] = "AutoMode"

                            tempDF["hashID"] = pumpSettings.loc[p, "hashID"]
                            tempDF["age"] = pumpSettings.loc[p, "age"]
                            tempDF["ylw"] = pumpSettings.loc[p, "ylw"]
                            sbr = pd.concat([sbr, tempDF[sbrCH]], ignore_index=True)


                        # %% ACTUAL BASAL RATES (TIME, VALUE, DURATION, TYPE (SCHEDULED, TEMP, SUSPEND))
                        if "basal" in data.type.unique():
                            basal = data[data.type == "basal"].copy().dropna(axis=1, how="all")
                            basal.sort_values("uploadTime", ascending=False, inplace=True)

                            basal, nBasalDuplicatesRemoved = \
                                td.clean.remove_duplicates(basal, basal[["deliveryType", "deviceTime", "duration", "rate"]])
                            metadata["basal.nBasalDuplicatesRemoved"] = nBasalDuplicatesRemoved

                            # fill NaNs with 0, as it indicates a suspend (temp basal of 0)
                            basal.rate.fillna(0, inplace=True)

                            # get rid of basals that have durations of 0
                            nBasalDuration0 = sum(basal.duration > 0)
                            basal = basal[basal.duration > 0]
                            metadata["basal.nBasalDuration0"] = nBasalDuration0

                            # get rid of basal durations that are unrealistic
                            nUnrealisticBasalDuration = ((basal.duration < 0) | (basal.duration > 86400000))
                            metadata["nUnrealisticBasalDuration"] = sum(nUnrealisticBasalDuration)
                            basal.loc[nUnrealisticBasalDuration, "duration"] = np.nan

                            # calculate the total amount of insulin delivered (duration * rate)
                            basal["durationHours"] = basal["duration"] / 1000.0 / 3600.0
                            basal["totalAmountOfBasalInsulin"] = basal["durationHours"] * basal["rate"]

                            # get a summary of basals per day
                            basalDaySummary = get_basalDaySummary(basal)


    # %% LOOP DATA (BINARY T/F)


    # %% CGM DATA


    # %% NUMBER OF DAYS OF PUMP AND CGM DATA, OVERALL AND PER EACH AGE & YLW


    # %% STATS PER EACH TYPE, OVERALL AND PER EACH AGE & YLW (MIN, PERCENTILES, MAX, MEAN, SD, IQR, COV)


    # %% SAVE RESULTS


    # %% MAKE THIS A FUNCTION SO THAT IT CAN BE RUN PER EACH INDIVIDUAL
                        else:
                            metadata["flags"] = "no basal data"
                    else:
                        metadata["flags"] = "no pump settings"
                else:
                    metadata["flags"] = "no bolus wizard data"
            else:
                metadata["flags"] = "no upload data"
        else:
            metadata["flags"] = "file contains no data"
    else:
        metadata["flags"] = "file does not exist"

    print("done with", dIndex)


# %% V2 DATA TO GRAB
# MAX BASAL RATE, MAX BOLUS AMOUNT, AND INSULIN DURATION SET ON SELECT PUMPS
# RE-EVALUATE THE WAY EXTENDED BOLUSES ARE BEING ACCOUNTED (ARE THEY ALSO SHOWING UP IN BASAL DATA?)
# ALERT SETTINGS
# ESTIMATED LOCAL TIME
# PUMP AND CGM DEVICE ()
# GLYCEMIC OUTCOMES
# DO NOT ROUND DATA
# INFUSION SITE CHANGES
# CGM CALIBRATIONS
