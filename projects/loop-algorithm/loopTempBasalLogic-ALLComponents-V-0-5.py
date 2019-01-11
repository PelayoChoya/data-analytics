#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
description: demonstrate the logic of the loop
version: 0.0.1
created: 2018-11-28
author: Ed Nykaza (original credit goes to Pete Schwamb, https://github.com/ps2/LoopExplain/blob/master/Loop%20Explain.ipynb)
dependencies:
    * requires tidepool-analytics environment (see readme for instructions)
    * requires San Francisco Fonts in a ./fonts folder
license: BSD-2-Clause
"""


# %% required libraries
import os
import sys
import pdb
import numpy as np
import pandas as pd
import datetime as dt
from scipy.interpolate import BSpline, make_interp_spline
from matplotlib import pyplot as plt
from matplotlib.legend_handler import HandlerLine2D
import matplotlib.font_manager as fm
import matplotlib.style as ms
ms.use("default")


# %% functions
def simulate_cgm_data(cgmTimesMinutes=[5, 120, 240, 360],
                      cgmValues_mgdL=[100, 95, 110, 105],
                      amountOfWiggle=3):

    inputCgm = pd.DataFrame(np.array([cgmTimesMinutes, cgmValues_mgdL]).T, columns=["time", "values"]).sort_values(by="time")
    simulatedTime = np.arange(inputCgm.time.min(), inputCgm.time.max() + 5, 5)
    splineProperties = make_interp_spline(inputCgm["time"].values,
                                          inputCgm["values"].values,
                                          k=amountOfWiggle)
    splineFit = BSpline(splineProperties.t, splineProperties.c, splineProperties.k)
    simulatedCgm = splineFit(simulatedTime)
    simulatedCgm[simulatedCgm <= 40] = 40
    simulatedCgm[simulatedCgm >= 400] = 400

    return simulatedTime, simulatedCgm


def make_hour_labels(startTimeHour, startTimeAMPM, hourTicks):
    labels = []
    if "AM" in startTimeAMPM:
        ampm = ["AM", "PM"]
    else:
        ampm = ["PM", "AM"]
    for label in hourTicks:
        hr = label + startTimeHour
        if hr == 0:
            hr = 12
            labels.append(("%d " + ampm[1]) % hr)
        elif hr == 12:
            labels.append(("%d " + ampm[1]) % hr)
        elif hr > 12:
            hr = hr - 12
            labels.append(("%d " + ampm[1]) % hr)

        else:  # case of ((hr >= 1) & (hr < 12)):
            labels.append(("%d " + ampm[0]) % hr)

    return labels


# %% insulin model functions
def exponentialModel(df, peakActivityTime, activeDuration=6):
    activeDurationMinutes = activeDuration * 60

    tau = (peakActivityTime *
           (1 - peakActivityTime / activeDurationMinutes) /
           (1 - 2 * peakActivityTime / activeDurationMinutes))
    a = 2 * tau / activeDurationMinutes
    S = 1 / (1 - a + (1 + a) * np.exp(-activeDurationMinutes / tau))

    df["iobPercent"] = (1 - S * (1 - a) *
      ((pow(df["minutesSinceDelivery"], 2) /
       (tau * activeDurationMinutes * (1 - a)) - df["minutesSinceDelivery"] / tau - 1) *
        np.exp(-df["minutesSinceDelivery"] / tau) + 1))

    return df


def get_insulin_effect(
        model="humalogNovologAdult",  # options are "walsh", "humalogNovologAdult",
        # "humalogNovologChild", "fiasp", or "exponentialCustom"
        activeDuration=6,  # in hours, only needs to be specified for walsh model,
        # can range between 2 to 8 hours in 15 minute increments
        peakActivityTime=np.nan,  # in minutes, only used for exponential model
        deliveryTime=dt.datetime.now(),  # date time of the insulin delivery
        insulinAmount=np.nan,  # units (U) of insulin delivered
        isf=np.nan,  # insulin sensitivity factor (mg/dL)/U
        effectLength=8,  # in hours, set to 8 because that is the max walsh model
        timeStepSize=5,  # in minutes, the resolution of the time series
        ):

    # specify the date range of the insulin effect time series
    startTime = pd.to_datetime(deliveryTime).round(str(timeStepSize) + "min")
    endTime = startTime + pd.Timedelta(8, unit="h")
    rng = pd.date_range(startTime, endTime, freq=(str(timeStepSize) + "min"))
    insulinEffect = pd.DataFrame(rng, columns=["dateTime"])

    insulinEffect["minutesSinceDelivery"] = np.arange(0, (effectLength * 60) + 1, timeStepSize)

    if "walsh" in model:
        if (activeDuration < 2) | (activeDuration > 8):
            sys.exit("invalid activeDuration, must be between 2 and 8 hours")
        elif activeDuration < 3:
            nearestActiveDuration = 3
        elif activeDuration > 6:
            nearestActiveDuration = 6
        else:
            nearestActiveDuration = round(activeDuration)

        # scale the time if the active duraiton is NOT 3, 4, 5, or 6 hours
        scaledMinutes = insulinEffect["minutesSinceDelivery"] * nearestActiveDuration / activeDuration

        if nearestActiveDuration == 3:

            # 3 hour model approximation
            insulinEffect["iobPercent"] = -3.2030e-9 * pow(scaledMinutes, 4) + \
                                            1.354e-6 * pow(scaledMinutes, 3) - \
                                            1.759e-4 * pow(scaledMinutes, 2) + \
                                            9.255e-4 * scaledMinutes + 0.99951

        elif nearestActiveDuration == 4:

            # 4 hour model approximation
            insulinEffect["iobPercent"] = -3.310e-10 * pow(scaledMinutes, 4) + \
                                            2.530e-7 * pow(scaledMinutes, 3) - \
                                            5.510e-5 * pow(scaledMinutes, 2) - \
                                            9.086e-4 * scaledMinutes + 0.99950

        elif nearestActiveDuration == 5:

            # 5 hour model approximation
            insulinEffect["iobPercent"] = -2.950e-10 * pow(scaledMinutes, 4) + \
                                            2.320e-7 * pow(scaledMinutes, 3) - \
                                            5.550e-5 * pow(scaledMinutes, 2) + \
                                            4.490e-4 * scaledMinutes + 0.99300
        elif nearestActiveDuration == 6:
            # 6 hour model approximation
            insulinEffect["iobPercent"] = -1.493e-10 * pow(scaledMinutes, 4) + \
                                            1.413e-7 * pow(scaledMinutes, 3) - \
                                            4.095e-5 * pow(scaledMinutes, 2) + \
                                            6.365e-4 * scaledMinutes + 0.99700
        else:
            sys.exit("this case should not happen")

    elif "humalogNovologAdult" in model:

        # peakActivityTime = 75 # 65, 55
        insulinEffect = exponentialModel(insulinEffect, 75)

    elif "humalogNovologChild" in model:

        # peakActivityTime = 75 # 65, 55
        insulinEffect = exponentialModel(insulinEffect, 65)

    elif "fiasp" in model:

        # peakActivityTime = 75 # 65, 55
        insulinEffect = exponentialModel(insulinEffect, 55)

    elif "exponentialCustom" in model:

        if peakActivityTime >= (activeDuration * 60):
            sys.exit("peak activity is greater than active duration, please note that " +
                     "peak activity is in minutes and active duration is in hours.")

        insulinEffect = exponentialModel(insulinEffect, peakActivityTime, activeDuration)

    # correct time at t=0
    insulinEffect.loc[insulinEffect["minutesSinceDelivery"] <= 0, "iobPercent"] = 1

    # correct times that are beyond the active duration
    insulinEffect.loc[insulinEffect["minutesSinceDelivery"] >= (activeDuration * 60), "iobPercent"] = 0

    # calculate the insulin on board
    insulinEffect["iob"] = insulinAmount * insulinEffect["iobPercent"]

    # calculate the change in blood glucose
    insulinEffect["cumulativeGlucoseEffect"] = -1 * (insulinAmount - insulinEffect["iob"]) * isf
    insulinEffect["deltaGlucoseEffect"] = \
        insulinEffect["cumulativeGlucoseEffect"] - insulinEffect["cumulativeGlucoseEffect"].shift()
    insulinEffect["deltaGlucoseEffect"].fillna(0, inplace=True)

    return insulinEffect


# %% define the exponential model
insulinModel = "humalogNovologAdult"
peakActivityTime = 60
activeDuration = 6
deliveryTime = dt.datetime.now()
insulinAmount = 2
isf = 50

insulinEffect = get_insulin_effect(model=insulinModel,
                                   peakActivityTime=peakActivityTime,
                                   activeDuration=activeDuration,
                                   deliveryTime=deliveryTime,
                                   insulinAmount=insulinAmount,
                                   isf=isf)

xData = insulinEffect["minutesSinceDelivery"]/60


# %% set figure properties
versionNumber = 0
subversionNumber = 5
figureClass = "LoopOverview-AllEffects" + "-" + \
    "V" + str(versionNumber) + "-" +str(subversionNumber)
outputPath = os.path.join(".", "figures")


# create output folder if it doesn't exist
if not os.path.isdir(outputPath):
    os.makedirs(outputPath)

figureSizeInches = (15, 7)
figureFont = fm.FontProperties(fname=os.path.join(".", "fonts",
                                                  "SF Compact", "SFCompactText-Bold.otf"))
font = {'weight': 'bold',
        'size': 15}

plt.rc('font', **font)
coord_color = "#c0c0c0"

xLabel = "Time Since Delivery (Hours)"
labelFontSize = 18
tickLabelFontSize = 15


# %% common figure elements across all figures
# speficy the correction range
correction_min = 90
correction_max = 120
suspendThreshold = 60
correction_target = np.mean([correction_min, correction_max])


def common_figure_elements(ax, xLabel, yLabel, figureFont, labelFontSize, tickLabelFontSize, coord_color, yLabel_xOffset=0.4):
    # x-axis items
    ax.set_xlabel(xLabel, fontsize=labelFontSize, color=coord_color)
    ax.set_xlim(0, 8)

    # define the spines and grid
    ax.spines['bottom'].set_color(coord_color)
    ax.spines['top'].set_color(coord_color)
    ax.spines['left'].set_color(coord_color)
    ax.spines['right'].set_color(coord_color)
    ax.spines['bottom'].set_visible(False)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.grid(ls='-', color=coord_color)

    # set size of ticklabels
    ax.tick_params(axis='both', labelsize=tickLabelFontSize, colors=coord_color)

    # define labels and limits
    ax.text(min(ax.get_xlim()) - yLabel_xOffset,
            max(ax.get_ylim()) + abs(max(ax.get_ylim()) - min(ax.get_ylim()))/25,
            yLabel, fontproperties=figureFont, size=labelFontSize)

    return ax


# %% retrospecitve correction

# specify the CGM Data (in minutes and mg/dL)
cgmTimes =  [5,    60, 120, 180, 240, 300, 350, 355, 360]
cgmValues = [100, 140, 180, 200, 210, 195, 200, 203, 206]
simulatedTime, simulatedCgm = simulate_cgm_data(cgmTimes, cgmValues, amountOfWiggle=2)

# specify the time you want the simulation to start
startTimeHour = 6
startTimeAMPM = "AM"

## %% apply the insulin effect
predictedTime = np.arange(360, 725, 5)
insulinCgm = simulatedCgm[-1] + (insulinEffect["cumulativeGlucoseEffect"][0:73].values)
predictedCgm = insulinCgm
## make up prediction from the insulin and carb effect over the last 30 minutes
#pred20minTime = np.append(360, simulatedTime[-1]+ np.cumsum(np.ones(4)*5))
#pred20minCgm = np.append(106, simulatedCgm[-1] + np.cumsum(np.ones(4)*6))
#
## momentum effect
#mTime = pred20minTime
#mCgm = np.append(106, np.array([109, 111, 112, 112]))
#
## blended effect
#predictedTime = pred20minTime
#predictedCgm = np.append(106, np.array([109, 113, 118, 124]))

# new format
figureName = "all-effect-example"
fig, ax = plt.subplots(figsize=figureSizeInches)
bgRange = (100, 400)
plt.ylim(bgRange)
ax.set_xlim([min(simulatedTime) - 5, max(predictedTime) + 15])
yLabel = "Glucose (mg/dL)"


# show the insulin delivered
ax.plot(predictedTime[0], insulinCgm[0] + 18,
        marker='v', markersize=10, color="#f09a37",
        ls="None", label="%d Unit of Insulin Delivered" % insulinAmount)

# plot predicted cgm from all insulin effect only
ax.plot(predictedTime, insulinCgm, linestyle="--", color="#f09a37", lw=2, label="Predicted Glucose (Insulin Only)")

# show the carbs delivered
ax.plot(predictedTime[0], insulinCgm[0] - 15,
        marker='^', markersize=10, color="#83D754",
        ls="None", label="72g of Carbs ")

carbCgm = np.append(insulinCgm[0], insulinCgm[0] + np.cumsum(np.ones(72)))
# plot predicted cgm from all insulin effect only
ax.plot(predictedTime, carbCgm, linestyle="--", color="#83D754", lw=2, label="Predicted Glucose (Carb Only)")


# retrospective correction
actual30min = simulatedCgm[-6:]
cgmTimes =  [335, 345, 360]
cgmValues = np.array([180, 190, 200]) + 18
pred30minTime, pred30minCgm = simulate_cgm_data(cgmTimes, cgmValues, amountOfWiggle=2)
# get the bg vel
bgVel = np.round(np.mean(pred30minCgm - actual30min))
rcTime = np.arange(5, 65, 5)
rcCgm = -bgVel * (1 - ((rcTime - 5)/55))

retroTime = np.append(360, rcTime+360)
retroCgm = np.append(simulatedCgm[-1], simulatedCgm[-1] + np.cumsum(rcCgm))

#ax.plot(pred30minTime, pred30minCgm, linestyle="-.", color="#3175FF", lw=2, label="Retrospective Forecast (BGvel=%d mg/dL per 5min)" % bgVel)
ax.scatter(pred30minTime, pred30minCgm, s=10, color="#3175FF", label="Retrospective Forecast (BGvel=%d mg/dL per 5min)" % bgVel)
ax.plot(retroTime, retroCgm, linestyle="--", color="#3175FF", lw=2, label="Predicted Glucose (RC Effect Only)")



## make up prediction from the insulin and carb effect over the last 30 minutes
#pred20minTime = np.append(360, simulatedTime[-1]+ np.cumsum(np.ones(4)*5))
#pred20minCgm = np.append(106, simulatedCgm[-1] + np.cumsum(np.ones(4)*6))


# plot slope
ax.plot(simulatedTime[-3:], simulatedCgm[-3:], linestyle="-.", color="#F05237", lw=2, label="Momentum Slope (3 mg/dL per 5min)")
mSlope = 3
# momentum effect
mTime = predictedTime[:5]
mCgm = np.append(simulatedCgm[-1], np.array([simulatedCgm[-1]+3, simulatedCgm[-1]+5,
                                            simulatedCgm[-1]+6, simulatedCgm[-1]+6]))
#
## blended effect
#predictedTime = pred20minTime
#predictedCgm = np.append(106, np.array([109, 113, 118, 124]))



# plot predicted cgm from momentum
ax.plot(mTime, mCgm, linestyle="--", color="#F05237", lw=2, label="Predicted Glucose (Momentum Effect Only)")
#
# plot predicted cgm from momentum
insulinVel = insulinCgm[1:5]-insulinCgm[0:4]
carbVel = carbCgm[1:5]-carbCgm[0:4]
retroVel = retroCgm[1:5]-retroCgm[0:4]
allVel = insulinVel + carbVel + retroVel
blendedAllVel = allVel*np.array([0, 0.3333, 0.6666, 1])

allBG = np.append(simulatedCgm[-1], simulatedCgm[-1] + np.cumsum(blendedAllVel))
allBGTime = predictedTime[:5]

# other effects
ax.plot(allBGTime, allBG, linestyle="--", color="#AC37f0", lw=2, label="Predicted Glucose (Insulin, Carb, & RC)")

# blended (this covers the first 20 minutes)
mVel = mCgm[1:5]-mCgm[0:4]
blendedVel = blendedAllVel + mVel
all20min = np.append(simulatedCgm[-1], simulatedCgm[-1] + np.cumsum(blendedVel))

# now do the next 40 minutes
insulinVel = insulinCgm[5:13]-insulinCgm[4:12]
carbVel = carbCgm[5:13]-carbCgm[4:12]
retroVel = retroCgm[5:13]-retroCgm[4:12]
allVel = insulinVel + carbVel + retroVel

all40min = np.append(all20min, all20min[-1] + np.cumsum(allVel))

# next do the remaining
insulinVel = insulinCgm[13:]-insulinCgm[12:-1]
carbVel = carbCgm[13:]-carbCgm[12:-1]
allVel = insulinVel + carbVel

predictedCgm = np.append(all40min, all40min[-1] + np.cumsum(allVel))

ax.plot(predictedTime, predictedCgm, linestyle="--", color="#31B0FF", lw=2, label="Predicted Glucose (All Effects)")

# plot simulated cgm
ax.scatter(simulatedTime, simulatedCgm, s=16, color="#31B0FF", label="CGM Data")

## plot correction range
#ax.fill_between([ax.get_xlim()[0], ax.get_xlim()[1] + 30],
#                [correction_min, correction_min],
#                [correction_max, correction_max],
#                facecolor='#B5E7FF', lw=0)
#
#ax.plot([], [], color='#B5E7FF', linewidth=10,
#        label="Correction Range = %d - %d" % (correction_min, correction_max))

## plot the Correction Target
#ax.plot(predictedTime[-1], correction_target,
#        marker='*', markersize=16, color="purple", alpha=0.5,
#        ls="None", label="Correction Target = %d" % correction_target)

## plot the current time
#ax.plot(simulatedTime[-1], simulatedCgm[-1],
#        marker='*', markersize=16, color=coord_color, markeredgecolor = "black", alpha=0.5,
#        ls="None", label="Current Time BG =  %d" % simulatedCgm[-1])
#
## plot eventual bg
#ax.plot(predictedTime[-1], predictedCgm[-1],
#        marker='*', markersize=16, color="#31B0FF", alpha=0.5,
#        ls="None", label="Eventual BG = %d" % predictedCgm[-1])

## find and plot minimum BG
#min_idx = np.argmin(predictedCgm)
#ax.plot(predictedTime[min_idx], predictedCgm[min_idx],
#        marker='*', markersize=16, color="red", alpha=0.25,
#        ls="None", label="Minimum Predicted BG = %d" % predictedCgm[min_idx])

## plot suspend threshold line
#ax.hlines(suspendThreshold, ax.get_xlim()[0], ax.get_xlim()[1],
#          colors="red", label="Suspend Threshold = %d" % suspendThreshold)

## place holder for the delta vertical line in the legend
#delta = int(predictedCgm[-1] - correction_target)
#ax.plot(-10, 10, ls="None", marker="|", markersize=16, markeredgewidth=6, alpha=0.5,
#        color="purple", label="Delta = %d" % delta)

# run the common figure elements here
ax = common_figure_elements(ax, xLabel, yLabel, figureFont, labelFontSize, tickLabelFontSize, coord_color, yLabel_xOffset=-280)

# change the order of the legend items
handles, labels = ax.get_legend_handles_labels()
#pdb.set_trace()
#handles = [handles[0], handles[7], handles[5], handles[2], handles[3], handles[4],
#           handles[6], handles[1]]
#labels = [labels[0], labels[7], labels[5], labels[2], labels[3], labels[4],
#           labels[6], labels[1]]

# format the legend
leg = ax.legend(handles, labels, scatterpoints=3, edgecolor="black", loc=1)
for text in leg.get_texts():
    text.set_color('#606060')
    text.set_weight('normal')
#    text.set_fontsize(12)

## plot the delta
#ax.vlines(predictedTime[-1] + 10, min([correction_target, predictedCgm[-1]]),
#          max([correction_target, predictedCgm[-1]]), linewidth=6, alpha=0.5, colors="purple")

# set tick marks
minuteTicks = np.arange(0, (len(simulatedTime) + len(predictedTime)+19) * 5 + 1, 60)
hourTicks = np.int64(minuteTicks / 60)
hourLabels = make_hour_labels(startTimeHour, startTimeAMPM, hourTicks)
ax.set_xticks(minuteTicks)
ax.set_xticklabels(hourLabels)


# extras for this plot
ax.set_xlabel("")
#plt.xlim([min(simulatedTime) - 15, max(predictedTime) + 30])
ax.set_xlim([300, 725])
ax.text(max(ax.get_xlim()),
        max(ax.get_ylim()) + 7,
        "Eventually %d mg/dL" % predictedCgm[-1],
        horizontalalignment="right", fontproperties=figureFont, size=labelFontSize, color=coord_color)



plt.savefig(os.path.join(outputPath, figureClass + figureName + "-WITH-LEGEND.png"))
plt.show()
plt.close('all')


