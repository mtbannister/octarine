from __future__ import absolute_import

import argparse
import logging
import math
import sys
import tempfile
import time

import ephem
import matplotlib
import requests
from astropy.io.votable import parse

matplotlib.use('Agg')
from matplotlib.pyplot import figure, close
from matplotlib.patches import Rectangle
from matplotlib.backends.backend_pdf import PdfPages

from src.daomop import (storage)
from src.planning import parameters

dbimages = 'vos:jkavelaars/CFIS/dbimages'
storage.DBIMAGES = dbimages

parameters.RUNIDS = ['17AP30', '17AP31']


def query_for_observations(mjd, observable, runids):
    """Do a QUERY on the TAP service for all observations that are part of runid, 
    where taken after mjd and have calibration 'observable'.

    Schema is at: http://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/tap/tables

    mjd : float 
    observable: str ( 2 or 1 )
    runid: tuple eg. ('13AP05', '13AP06')

    """

    data = {"QUERY": ("SELECT Observation.target_name as TargetName, "
                      "COORD1(CENTROID(Plane.position_bounds)) AS RA,"
                      "COORD2(CENTROID(Plane.position_bounds)) AS DEC, "
                      "Plane.time_bounds_lower AS StartDate, "
                      "Plane.time_exposure AS ExposureTime, "
                      "Observation.instrument_name AS Instrument, "
                      "Plane.energy_bandpassName AS Filter, "
                      "Observation.observationID AS dataset_name, "
                      "Observation.proposal_id AS ProposalID, "
                      "Observation.proposal_pi AS PI "
                      "FROM caom2.Observation AS Observation "
                      "JOIN caom2.Plane AS Plane ON "
                      "Observation.obsID = Plane.obsID "
                      "WHERE  ( Observation.collection = 'CFHT' ) "
                      "AND Plane.time_bounds_lower > %d "
                      "AND Plane.calibrationLevel=%s "
                      "AND Observation.proposal_id IN %s " ) %
                     ( mjd, observable, str(runids)),
            "REQUEST": "doQuery",
            "LANG": "ADQL",
            "FORMAT": "votable"}

    result = requests.get(storage.TAP_WEB_SERVICE, params=data, verify=False)
    assert isinstance(result, requests.Response)
    logging.debug("Doing TAP Query using url: %s" % (str(result.url)))
    tmpFile = tempfile.NamedTemporaryFile()
    with open(tmpFile.name, 'w') as outfile:
        outfile.write(result.text)
    try:
       vot = parse(tmpFile.name).get_first_table()
    except:
       print result.text
       raise

    vot.array.sort(order='StartDate')
    t = vot.array
    tmpFile.close()


    logging.debug("Got {} lines from tap query".format(len(t)))

    return t


def create_ascii_table(obsTable, outfile):
    """Given a table of observations create an ascii log file for easy parsing.
    Store the result in outfile (could/should be a vospace dataNode)

    obsTable: astropy.votable.array object
    outfile: str (target_name of the vospace dataNode to store the result to)

    """

    logging.info("writing text log to %s" % ( outfile))

    stamp = "#\n# Last Updated: " + time.asctime() + "\n#\n"
    header = "| %20s | %20s | %20s | %20s | %20s | %20s | %20s |\n" % (
        "EXPNUM", "OBS-DATE", "FIELD", "EXPTIME(s)", "RA", "DEC", "RUNID")
    bar = "=" * (len(header) - 1) + "\n"

    if outfile[0:4] == "vos:":
        tmpFile = tempfile.NamedTemporaryFile(suffix='.txt')
        fout = tmpFile
    else:
        fout = open(outfile, 'w')

    t2 = None
    fout.write(bar + stamp + bar + header)

    populated = storage.list_dbimages(dbimages=dbimages)
    for i in range(len(obsTable) - 1, -1, -1):
        row = obsTable.data[i]
        if row['dataset_name'] not in populated:
            storage.populate(row['dataset_name'])
        sDate = str(ephem.date(row.StartDate +
                               2400000.5 -
                               ephem.julian_date(ephem.date(0))))[:20]
        t1 = time.strptime(sDate, "%Y/%m/%d %H:%M:%S")
        if t2 is None or math.fabs(time.mktime(t2) - time.mktime(t1)) > 3 * 3600.0:
            fout.write(bar)
        t2 = t1
        ra = str(ephem.hours(math.radians(row.RA)))
        dec = str(ephem.degrees(math.radians(row.DEC)))
        line = "| %20s | %20s | %20s | %20.1f | %20s | %20s | %20s |\n" % (
            str(row.dataset_name),
            str(ephem.date(row.StartDate + 2400000.5 -
                           ephem.julian_date(ephem.date(0))))[:20],
            row.TargetName[:20],
            row.ExposureTime, ra[:20], dec[:20], row.ProposalID[:20] )
        fout.write(line)

    fout.write(bar)

    if outfile[0:4] == "vos:":
        fout.flush()
        storage.copy(tmpFile.name, outfile)
    fout.close()

    return


def create_sky_plot(obstable, outfile, night_count=1, stack=True):
    """Given a VOTable that describes the observation coverage provide a PDF of the skycoverge.

    obstable: vostable.arrary
    stack: BOOL (true: stack all the observations in a series of plots)

    """

    # camera dimensions
    width = 0.98
    height = 0.98

    if outfile[0:4] == 'vos:':
        tmpFile = tempfile.NamedTemporaryFile(suffix='.pdf')
        pdf = PdfPages(tmpFile.name)
    else:
        pdf = PdfPages(outfile)

    saturn = ephem.Saturn()
    uranus = ephem.Uranus()

    t2 = None
    fig = None
    proposalID = None
    limits = {'13A': ( 245, 200, -20, 0),
              '13B': ( 0, 45, 0, 20)}
    for row in reversed(obstable.data):
        date = ephem.date(row.StartDate + 2400000.5 - ephem.julian_date(ephem.date(0)))
        sDate = str(date)
        # Saturn only a problem in 2013A fields
        saturn.compute(date)
        sra = math.degrees(saturn.ra)
        sdec = math.degrees(saturn.dec)
        uranus.compute(date)
        ura = math.degrees(uranus.ra)
        udec = math.degrees(uranus.dec)
        t1 = time.strptime(sDate, "%Y/%m/%d %H:%M:%S")
        if t2 is None or (math.fabs(time.mktime(t2) - time.mktime(
                t1)) > 3 * 3600.0 and opt.stack) or proposalID is None or proposalID != row.ProposalID:
            if fig is not None:
                pdf.savefig()
                close()
            proposalID = row.ProposalID
            fig = figure(figsize=(7, 2))
            ax = fig.add_subplot(111, aspect='equal')
            ax.set_title("Data taken on %s-%s-%s" % ( t1.tm_year, t1.tm_mon, t1.tm_mday), fontdict={'fontsize': 8})
            ax.axis(limits.get(row.ProposalID[0:3], (0, 20, 0, 20)))  # appropriate only for 2013A fields
            ax.grid()
            ax.set_xlabel("RA (deg)", fontdict={'fontsize': 8})
            ax.set_ylabel("DEC (deg)", fontdict={'fontsize': 8})
        t2 = t1
        ra = row.RA - width / 2.0
        dec = row.DEC - height / 2.0
        color = 'b'
        if 'W' in row['TargetName']:
            color = 'g'
        ax.add_artist(Rectangle(xy=(ra, dec), height=height, width=width,
                                edgecolor=color, facecolor=color,
                                lw=0.5, fill='g', alpha=0.33))
        ax.add_artist(Rectangle(xy=(sra, sdec), height=0.3, width=0.3,
                                edgecolor='r',
                                facecolor='r',
                                lw=0.5, fill='k', alpha=0.33))
        ax.add_artist(Rectangle(xy=(ura, udec), height=0.3, width=0.3,
                                edgecolor='b',
                                facecolor='b',
                                lw=0.5, fill='b', alpha=0.33))

    if ax is not None:
        ax.axis((270, 215, -20, 0))
        pdf.savefig()
        close()
    pdf.close()
    if outfile[0:4] == "vos:":
        storage.copy(tmpFile.name, outfile)
        tmpFile.close()

    return


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Query the CADC for OSSOS observations.")

    parser.add_argument('date', nargs='?', action='store',
                        default=parameters.SURVEY_START)

    parser.add_argument('--runid', nargs='*', action='store',
                        default=parameters.RUNIDS)

    parser.add_argument('--cal', action='store', default=1)

    parser.add_argument('--outfile', action='store',
                        default='vos:OSSOS/ObservingStatus/obsList')

    parser.add_argument('--debug', action='store_true')

    parser.add_argument('--stack', action='store_true', default=False,
                        help=( "Make single status plot that stacks"
                               " data accross multiple nights, instead of nightly sub-plots." ))

    opt = parser.parse_args()

    runids = tuple(opt.runid)

    if opt.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.ERROR)

    try:
        mjd_yesterday = ephem.date(ephem.julian_date(ephem.date(opt.date))) - 2400000.5
    except Exception as e:
        logging.error("you said date = %s" % (opt.date))
        logging.error(str(e))
        sys.exit(-1)


    obs_table = query_for_observations(mjd_yesterday, opt.cal, runids)

    create_ascii_table(obs_table, opt.outfile + ".txt")

    # create_sky_plot(obs_table, opt.outfile + ".pdf", stack=opt.stack)
