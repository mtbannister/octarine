"""Mark the stationary sources in a given source catalog by matching with other source catalogs"""
import sys
import errno
import storage
import util
from astropy.io import fits
from astropy.coordinates import SkyCoord
from astropy.table import vstack
import numpy
import argparse
import logging

task = "stationary"
dependency = None


def run(expnum, ccd, prefix, version, dry_run, force):
    """
    Retrieve the catalog from VOSspace, find the matching dataset_name/ccd combos and match against those.

    :param ccd: chip to retrieve for matching
    :param expnum: exposure number to retrieve for match
    :param force:
    :param dry_run:
    :param version:
    :param prefix:
    """
    message = storage.SUCCESS

    if storage.get_status(task, prefix, expnum, version=version, ccd=ccd) and not force:
        logging.info("{} completed successfully for {} {} {} {}".format(task, prefix, expnum, version, ccd))
        return

    with storage.LoggingManager(task, prefix, expnum, ccd, version, dry_run):
        try:
            if dependency is not None and not storage.get_status(dependency, prefix, 
                                                                 expnum, "p", ccd=ccd):
                raise IOError("{} not yet run for {}".format(dependency, expnum))

            # get catalog from the vospace storage area
            logging.info("Getting fits image from VOSpace")

            logging.info("Running match on %s %d" % (expnum, ccd))
            catalog = match(expnum, ccd)
            split_to_hpx(catalog)

            if dry_run:
                return

            # place the results into VOSpace
            logging.info(message)
        except Exception as e:
            print type(e)
            message = str(e)
            logging.error(message)

        storage.set_status(task, prefix, expnum, version, ccd=ccd, status=message)


def split_to_hpx(catalog):

    dataset_name = "{}{}{}".format(catalog.observation.dataset_name, catalog.version, catalog.ccd)
    image = storage.Image(catalog.observation, ccd=catalog.ccd, version=catalog.version)
    catalog.table['dataset_name'] = len(catalog.table)*[dataset_name]
    catalog.table['mid_mjdate'] = image.header['MJDATE'] + image.header['EXPTIME']/24./3600.0

    for pix in numpy.unique(catalog.table['HEALPIX']):
        healpix_catalog = storage.HPXCatalog(pixel=pix)
        try:
            healpix_catalog.get()
            healpix_catalog.table = healpix_catalog.table[healpix_catalog.table['dataset_name'] != dataset_name]
            healpix_catalog.table = vstack([healpix_catalog.table, catalog.table[catalog.table['HEALPIX'] == pix]])
        except OSError as ex:
            if ex.errno == errno.ENOENT:
                healpix_catalog.hdulist = fits.HDUList()
                healpix_catalog.hdulist.append(catalog.hdulist[0])
                healpix_catalog.table = catalog.table[catalog.table['HEALPIX'] == pix]
            else:
                raise ex
        healpix_catalog.write()
        healpix_catalog.put()


def match(expnum, ccd):

    observation = storage.Observation(expnum)
    image = storage.Image(observation, ccd=ccd)

    match_list = image.polygon.cone_search(runids=storage.RUNIDS,
                                           minimum_time=2.0/24.0,
                                           mjdate=image.header.get('MJDATE', None))

    catalog = storage.FitsTable(observation, ccd=ccd, ext='.cat.fits')
    # First match against the HPX catalogs (if they exist)
    ra_dec = SkyCoord(catalog.table['X_WORLD'],
                      catalog.table['Y_WORLD'],
                      unit=('degree', 'degree'))
    catalog.table['HEALPIX'] = util.skycoord_to_healpix(ra_dec)
    # reshape the position vectors from the catalogues for use in match_lists
    p1 = numpy.transpose((catalog.table['X_WORLD'],
                          catalog.table['Y_WORLD']))

    # Build the HPXID column by matching against the HPX catalogs that might exit.
    catalog.table['HPXID'] = -1
    for healpix in numpy.unique(catalog.table['HEALPIX']):
        hpx_cat = storage.HPXCatalog(pixel=healpix)
        hpx_cat_len = 0
        try:
            hpx_cat.get()
            p2 = numpy.transpose((hpx_cat.table['X_WORLD'],
                                  hpx_cat.table['Y_WORLD']))
            idx1, idx2 = util.match_lists(p1, p2, tolerance=0.5 / 3600.0)
            catalog.table['HPXID'][idx2.data[~idx2.mask]] = hpx_cat.table['HPXID'][~idx2.mask]
            hpx_cat_len = len(hpx_cat.table)
        except OSError as ose:
            if ose.errno != errno.ENOENT:
                raise ose
        # for all non-matched sources in this healpix we increment the counter.
        cond = numpy.all((catalog.table['HPXID'] < 0,
                          catalog.table['HEALPIX'] == healpix), axis=0)
        catalog.table['HPXID'][cond] = [hpx_cat_len + numpy.arange(cond.sum()), ]

    catalog.table['MATCHES'] = 0
    catalog.table['OVERLAPS'] = 0
    for match_set in match_list:
        logging.info("trying to match against catalog {}p{:02d}.cat.fits".format(match_set[0], match_set[1]))
        try:
            match_catalog = storage.FitsTable(storage.Observation(match_set[0]), ccd=match_set[1], ext='.cat.fits')
            match_image = storage.Image(storage.Observation(match_set[0]), ccd=match_set[1])
            # reshape the position vectors from the catalogues for use in match_lists
            p2 = numpy.transpose((match_catalog.table['X_WORLD'],
                                  match_catalog.table['Y_WORLD']))
            idx1, idx2 = util.match_lists(p1, p2, tolerance=0.5/3600.0)
            catalog.table['MATCHES'][idx2.data[~idx2.mask]] += 1
            catalog.table['OVERLAPS'] += \
                [match_image.polygon.isInside(row['X_WORLD'], row['Y_WORLD']) for row in catalog.table]
        except OSError as ioe:
            if ioe.errno == errno.ENOENT:
                logging.info(str(ioe))
                continue
            raise ioe

    return catalog



def main():
    parser = argparse.ArgumentParser(
        description='Create a matches column in a source catalog to determine if a source is a stationary object.')

    parser.add_argument("--dbimages",
                        action="store",
                        default="vos:cfis/solar_system/dbimages",
                        help='vospace dbimages containerNode')
    parser.add_argument("healpix",
                        type=int,
                        nargs='+',
                        help="healpix to process")
    parser.add_argument("--dry-run",
                        action="store_true",
                        help="DRY RUN, don't copy results to VOSpace, implies --force")
    parser.add_argument("--verbose", "-v",
                        action="store_true")
    parser.add_argument("--force", default=False,
                        action="store_true")
    parser.add_argument("--debug", "-d",
                        action="store_true")

    cmd_line = " ".join(sys.argv)
    args = parser.parse_args()

    util.set_logger(args)
    logging.info("Started {}".format(cmd_line))

    storage.DBIMAGES = args.dbimages
    prefix = ''
    version = 'p'

    exit_code = 0
    overlaps = storage.MyPolygon.from_healpix(args.healpix).cone_search(runids=storage.RUNIDS)
    for overlap in overlaps:
        expnum = overlap[0]
        ccd = overlap[1]
        run(expnum, ccd, prefix, version, args.dry_run, args.force)
    return exit_code



if __name__ == '__main__':
    sys.exit(main())
