#!/usr/bin/env python
"""
General comparison of 2-d model fields against data.  Currently only supports
sea surface temperature (sst), sea surface salinity (sss) and mixed layer
depth (mld)

Author: Luke Van Roekel, Milena Veneziani, Xylar Asay-Davis
Last Modified: 02/02/2017
"""

import matplotlib.pyplot as plt
import matplotlib.colors as cols

import numpy as np
import xarray as xr
import datetime
from netCDF4 import Dataset as netcdf_dataset
from mpl_toolkits.basemap import maskoceans

from ..shared.mpas_xarray.mpas_xarray import preprocess_mpas, \
    remove_repeated_time_index
from ..shared.plot.plotting import plot_global_comparison
from ..shared.interpolation.interpolate import interp_fields, init_tree
from ..shared.constants import constants

from ..shared.io import NameList, StreamsFile
from ..shared.io.utility import buildConfigFullPath


def ocn_modelvsobs(config, field, streamMap=None, variableMap=None):

    """
    Plots a comparison of ACME/MPAS output to SST or MLD observations

    config is an instance of MpasAnalysisConfigParser containing configuration
    options.

    field is the name of a field to be analyize (currently one of 'sst', 'sss'
    or 'mld')

    If present, streamMap is a dictionary of MPAS-O stream names that map to
    their mpas_analysis counterparts.

    If present, variableMap is a dictionary of MPAS-O variable names that map
    to their mpas_analysis counterparts.

    Authors: Luke Van Roekel, Milena Veneziani, Xylar Asay-Davis
    Last Modified: 02/02/2017
    """

    # read parameters from config file
    inDirectory = config.get('input', 'baseDirectory')

    namelistFileName = config.get('input', 'oceanNamelistFileName')
    namelist = NameList(namelistFileName, path=inDirectory)

    streamsFileName = config.get('input', 'oceanStreamsFileName')
    streams = StreamsFile(streamsFileName, streamsdir=inDirectory)

    calendar = namelist.get('config_calendar_type')

    # get a list of timeSeriesStats output files from the streams file,
    # reading only those that are between the start and end dates
    startDate = config.get('climatology', 'startDate')
    endDate = config.get('climatology', 'endDate')
    streamName = streams.find_stream(streamMap['timeSeriesStats'])
    inputFiles = streams.readpath(streamName, startDate=startDate,
                                  endDate=endDate, calendar=calendar)
    print 'Reading files {} through {}'.format(inputFiles[0], inputFiles[-1])

    plotsDirectory = buildConfigFullPath(config, 'output', 'plotsSubdirectory')
    observationsDirectory = buildConfigFullPath(config, 'oceanObservations',
                                                '{}Subdirectory'.format(field))
    mainRunName = config.get('runs', 'mainRunName')

    try:
        restartFile = streams.readpath('restart')[0]
    except ValueError:
        raise IOError('No MPAS-O restart file found: need at least one '
                      'restart file for ocn_modelvsobs calculation')

    startYear = config.getint('climatology', 'startYear')
    endYear = config.getint('climatology', 'endYear')
    yearOffset = config.getint('time', 'yearOffset')

    sectionName = 'regridded{}'.format(field.upper())
    outputTimes = config.getExpression(sectionName, 'comparisonTimes')

    ncFile = netcdf_dataset(restartFile, mode='r')
    lonCell = ncFile.variables["lonCell"][:]
    latCell = ncFile.variables["latCell"][:]
    ncFile.close()

    varList = [field]

    if field == 'mld':

        selvals = None

        # Load MLD observational data
        obsFileName = "{}/holtetalley_mld_climatology.nc".format(
                observationsDirectory)
        dsObs = xr.open_mfdataset(obsFileName)

        # Increment month value to be consistent with the model output
        dsObs.iMONTH.values += 1

        # Rename the time dimension to be consistent with the SST dataset
        dsObs.rename({'month': 'calmonth'}, inplace=True)
        dsObs.rename({'iMONTH': 'month'}, inplace=True)
        dsObs.coords['month'] = dsObs['calmonth']

        obsFieldName = 'mld_dt_mean'

        # Reorder dataset for consistence
        dsObs = dsObs.transpose('month', 'iLON', 'iLAT')

        # Set appropriate MLD figure labels
        observationTitleLabel = \
            "Observations (HolteTalley density threshold MLD)"
        outFileLabel = "mldHolteTalleyARGO"
        unitsLabel = 'm'

    elif field == 'sst':

        selvals = {'nVertLevels': 0}

        obsFileName = \
            "{}/MODEL.SST.HAD187001-198110.OI198111-201203.nc".format(
                    observationsDirectory)
        dsObs = xr.open_mfdataset(obsFileName)
        # Select years for averaging (pre-industrial or present-day)
        # This seems fragile as definitions can change
        if yearOffset < 1900:
            timeStart = datetime.datetime(1870, 1, 1)
            timeEnd = datetime.datetime(1900, 12, 31)
            preindustrialText = "pre-industrial 1870-1900"
        else:
            timeStart = datetime.datetime(1990, 1, 1)
            timeEnd = datetime.datetime(2011, 12, 31)
            preindustrialText = "present-day 1990-2011"

        dsTimeSlice = dsObs.sel(time=slice(timeStart, timeEnd))
        monthlyClimatology = dsTimeSlice.groupby('time.month').mean('time')

        # Rename the observation data for code compactness
        dsObs = monthlyClimatology.transpose('month', 'lon', 'lat')
        obsFieldName = 'SST'

        # Set appropriate figure labels for SST
        observationTitleLabel = \
            "Observations (Hadley/OI, {})".format(preindustrialText)
        outFileLabel = "sstHADOI"
        unitsLabel = r'$^o$C'

    elif field == 'sss':

        selvals = {'nVertLevels': 0}

        obsFileName = "{}/Aquarius_V3_SSS_Monthly.nc".format(
                observationsDirectory)
        dsObs = xr.open_mfdataset(obsFileName)

        timeStart = datetime.datetime(2011, 8, 1)
        timeEnd = datetime.datetime(2014, 12, 31)

        dsTimeSlice = dsObs.sel(time=slice(timeStart, timeEnd))

        # The following line converts from DASK to numpy to supress an odd
        # warning that doesn't influence the figure output
        dsTimeSlice.SSS.values

        monthlyClimatology = dsTimeSlice.groupby('time.month').mean('time')

        # Rename the observation data for code compactness
        dsObs = monthlyClimatology.transpose('month', 'lon', 'lat')
        obsFieldName = 'SSS'

        # Set appropriate figure labels for SSS
        preindustrialText = "2011-2014"

        observationTitleLabel = "Observations (Aquarius, {})".format(
                preindustrialText)
        outFileLabel = 'sssAquarius'
        unitsLabel = 'PSU'

    ds = xr.open_mfdataset(
        inputFiles,
        preprocess=lambda x: preprocess_mpas(x, yearoffset=yearOffset,
                                             timestr='Time',
                                             onlyvars=varList,
                                             selvals=selvals,
                                             varmap=variableMap))
    ds = remove_repeated_time_index(ds)

    timeStart = datetime.datetime(yearOffset+startYear, 1, 1)
    timeEnd = datetime.datetime(yearOffset+endYear, 12, 31)
    dsTimeSlice = ds.sel(Time=slice(timeStart, timeEnd))
    monthlyClimatology = dsTimeSlice.groupby('Time.month').mean('Time')

    latData, lonData = np.meshgrid(dsObs.lat.values,
                                   dsObs.lon.values)

    lonInds = np.where(dsObs.lon.values > 180.)
    lonT = dsObs.lon.values
    lonT[lonInds] -= 360.0

    latMesh, lonMesh = np.meshgrid(dsObs.lat.values, lonT)
    # Generate a land sea mask for appropriate error means
    lsmask1 = maskoceans(lonMesh,latMesh,np.ones((lonMesh.shape[0],lonMesh.shape[1])))
    #store ocean points for average
    oceanPoints = np.where(lsmask1 == False)


    latData = latData.flatten()
    lonData = lonData.flatten()

    daysarray = np.ones((12,
                         dsObs[obsFieldName].values.shape[1],
                         dsObs[obsFieldName].values.shape[2]))

    for monthIndex, dval in enumerate(constants.dinmonth):
        daysarray[monthIndex, :, :] = dval
        inds = np.where(np.isnan(
                dsObs[obsFieldName][monthIndex, :, :].values))
        daysarray[monthIndex, inds[0], inds[1]] = np.NaN

    # initialize interpolation variables
    d2, inds2, lonTarg, latTarg = init_tree(np.rad2deg(lonCell),
                                            np.rad2deg(latCell),
                                            constants.lonmin,
                                            constants.lonmax,
                                            constants.latmin,
                                            constants.latmax,
                                            constants.dLongitude,
                                            constants.dLatitude)
    d, inds, lonTargD, latTargD = init_tree(lonData, latData,
                                            constants.lonmin,
                                            constants.lonmax,
                                            constants.latmin,
                                            constants.latmax,
                                            constants.dLongitude,
                                            constants.dLatitude)
    nLon = lonTarg.shape[0]
    nLat = lonTarg.shape[1]

    modelOutput = np.zeros((len(outputTimes), nLon, nLat))
    observations = np.zeros((len(outputTimes), nLon, nLat))
    bias = np.zeros((len(outputTimes), nLon, nLat))
    meanBias = np.zeros(len(outputTimes))
    RMSE = np.zeros(len(outputTimes))
    meanModel = np.zeros(len(outputTimes))
    meanObs = np.zeros(len(outputTimes))

    # Interpolate and compute biases
    for timeIndex, timestring in enumerate(outputTimes):
        monthsValue = constants.monthdictionary[timestring]

        if isinstance(monthsValue, (int, long)):
            modelData = monthlyClimatology.sel(month=monthsValue)[field].values
            obsData = dsObs.sel(
                    month=monthsValue)[obsFieldName].values
        else:

            modelData = (np.sum(
                constants.dinmonth[monthsValue-1] *
                monthlyClimatology.sel(month=monthsValue)[field].values.T,
                axis=1) /
                np.sum(constants.dinmonth[monthsValue-1]))
            obsData = \
                (np.nansum(
                        daysarray[monthsValue-1, :, :] *
                        dsObs.sel(month=monthsValue)[obsFieldName].values,
                        axis=0) /
                 np.nansum(daysarray[monthsValue-1, :, :], axis=0))

        modelOutput[timeIndex, :, :] = interp_fields(modelData, d2, inds2,
                                                     lonTarg)
        observations[timeIndex, :, :] = interp_fields(obsData.flatten(), d,
                                                      inds, lonTargD)

        meanModel[timeIndex] = np.mean(modelOutput[timeIndex, oceanPoints[0], oceanPoints[1]])
        meanObs[timeIndex] = np.mean(observations[timeIndex, oceanPoints[0], oceanPoints[1]])


    for timeIndex in range(len(outputTimes)):
        bias[timeIndex, :, :] = (modelOutput[timeIndex, :, :] -
                                 observations[timeIndex, :, :])

        #Compute RMSE bias and mean bias
        meanBias[timeIndex] = np.mean(bias[timeIndex, oceanPoints[0], oceanPoints[1]])

        squareBias = bias[timeIndex,oceanPoints[0], oceanPoints[1]]**2
        meanSquareBias = np.mean(squareBias)
        RMSE[timeIndex] = np.sqrt(meanSquareBias)


    resultContourValues = config.getExpression(sectionName,
                                               'resultContourValues')
    resultColormap = plt.get_cmap(config.get(sectionName, 'resultColormap'))
    resultColormapIndices = config.getExpression(sectionName,
                                                 'resultColormapIndices')
    resultColormap = cols.ListedColormap(resultColormap(resultColormapIndices),
                                         "resultColormap")
    differenceContourValues = config.getExpression(sectionName,
                                                   'differenceContourValues')
    differenceColormap = plt.get_cmap(config.get(sectionName,
                                                 'differenceColormap'))
    differenceColormapIndices = config.getExpression(
            sectionName, 'differenceColormapIndices')
    differenceColormap = cols.ListedColormap(
            differenceColormap(differenceColormapIndices),
            "differenceColormap")

    for timeIndex in range(len(outputTimes)):
        meanModelLab =  'Mean: {:.2f}'.format(meanModel[timeIndex])
        meanObsLab = 'Mean: {:.2f}'.format(meanObs[timeIndex])
        meanBiasLab = 'Mean: {:.2f}'.format(meanBias[timeIndex])
        rmseLab = 'RMSE: {:.2f}'.format(RMSE[timeIndex])

        outFileName = "{}/{}_{}_{}_years{:04d}-{:04d}.png".format(
                plotsDirectory, outFileLabel, mainRunName,
                outputTimes[timeIndex], startYear, endYear)
        title = "{} ({}, years {:04d}-{:04d})".format(
                field.upper(), outputTimes[timeIndex], startYear, endYear)
        plot_global_comparison(config,
                               lonTarg,
                               latTarg,
                               modelOutput[timeIndex, :, :],
                               observations[timeIndex, :, :],
                               bias[timeIndex, :, :],
                               resultColormap,
                               resultContourValues,
                               differenceColormap,
                               differenceContourValues,
                               fileout=outFileName,
                               title=title,
                               modelTitle="{}".format(mainRunName),
                               obsTitle=observationTitleLabel,
                               diffTitle="Model-Observations",
                               cbarlabel=unitsLabel,
                               meanModelLabel=meanModelLab,
                               meanObsLabel=meanObsLab,
                               meanBiasLabel=meanBiasLab,
                               RMSELabel = rmseLab
                               )
