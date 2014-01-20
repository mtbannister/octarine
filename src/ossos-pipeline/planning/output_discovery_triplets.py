__author__ = 'Michele Bannister   git:@mtbannister'

import sqlalchemy as sa
# import web.field_obs.queries


class OssuaryTable(object):

	def __init__(self, tablename):
		# reflect_table_from_ossuary
		# Development testing database on local machine provided by Postgres.App
		engine = sa.create_engine('postgresql://localhost/ossuary', echo=False)
		metadata = sa.MetaData(bind=engine)
		table = sa.Table(tablename, metadata, autoload=True, autoload_with=engine)  # reflect existing table
		conn = engine.connect()

		self.tablename = tablename
		self.table = table
		self.conn = conn

class ImagesQuery(object):
    def __init__(self):
        """
        An ImagesQuery allows queries to ossuary's images table, and marshalls vtags associated with each image.
        """
        ot = OssuaryTable('images')
        self.images = ot.table
        self.conn = ot.conn

ims = ImagesQuery()
outfile = '13AO_triplets_details.txt'

with open('O_13A_discovery_expnums.txt', 'r') as infile:
    it = ims.images

    with open(outfile, 'w') as ofile:
        ofile.write('Expnum RA DEC Obs_end MJD_end Exptime\n'.format())

    for triplet in infile.readlines():
        # this should have two versions, a very precise one for use with the updated headers
        # and a straightforward version for use with the initial stuff that's in the database,
        # which allows use without VOSpace.
        with open(outfile, 'a') as ofile:  # blank line between triplets
            ofile.write('{}'.format(triplet.split(' ')[3]))

        for expnum in triplet.split(' ')[0:3]:
            ss = sa.select([it.c.image_id, it.c.crval_ra, it.c.crval_dec, it.c.obs_end, it.c.mjd_end, it.c.exptime],
                           order_by=it.c.image_id)
            ss.append_whereclause(ims.images.c.image_id == expnum)
            query = ims.conn.execute(ss)
            retval = [s for s in query][0]

            with open(outfile, 'a') as ofile:
                # expnum, ra, dec, obs_end, mjd_end, exptime
                ofile.write('{} {} {} {} {} {}\n'.format(*retval))

        with open(outfile, 'a') as ofile:  # blank line between triplets
            ofile.write('\n')