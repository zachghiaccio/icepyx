import datetime as dt
import earthaccess
import os
import json
import warnings
import pprint
import time
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

import icepyx.core.APIformatting as apifmt
import icepyx.core.is2ref as is2ref
import icepyx.core.granules as granules
from icepyx.core.granules import Granules as Granules

# QUESTION: why doesn't from granules import Granules as Granules work, since granules=icepyx.core.granules?
# from icepyx.core.granules import Granules
from icepyx.core.variables import Variables as Variables
import icepyx.core.validate_inputs as val
import icepyx.core.spatial as spat
from icepyx.core.visualization import Visualize


class GenQuery:
    """
    Base class for querying data.

    Generic components of query object that specifically handles
    spatio-temporal constraints applicable to all datasets.
    Extended by Query (ICESat-2) and Quest (other products).

    Parameters
    ----------
    spatial_extent : list of coordinates or string (i.e. file name)
        Spatial extent of interest, provided as a bounding box, list of polygon coordinates, or
        geospatial polygon file.
        NOTE: Longitude values are assumed to be in the range -180 to +180,
        with 0 being the Prime Meridian (Greenwich). See xdateline for regions crossing the date line.
        You can submit at most one bounding box or list of polygon coordinates.
        Per NSIDC requirements, geospatial polygon files may only contain one feature (polygon).
        Bounding box coordinates should be provided in decimal degrees as
        [lower-left-longitude, lower-left-latitute, upper-right-longitude, upper-right-latitude].
        Polygon coordinates should be provided as coordinate pairs in decimal degrees as
        [(longitude1, latitude1), (longitude2, latitude2), ... (longitude_n,latitude_n), (longitude1,latitude1)]
        or
        [longitude1, latitude1, longitude2, latitude2, ... longitude_n,latitude_n, longitude1,latitude1].
        Your list must contain at least four points, where the first and last are identical.
        Geospatial polygon files are entered as strings with the full file path and
        must contain only one polygon with the area of interest.
        Currently supported formats are: kml, shp, and gpkg
    date_range : list of 'YYYY-MM-DD' strings
        Date range of interest, provided as start and end dates, inclusive.
        The required date format is 'YYYY-MM-DD' strings, where
        YYYY = 4 digit year, MM = 2 digit month, DD = 2 digit day.
        Currently, a list of specific dates (rather than a range) is not accepted.
        TODO: accept date-time objects, dicts (with 'start_date' and 'end_date' keys, and DOY inputs).
        TODO: allow searches with a list of dates, rather than a range.
    start_time : HH:mm:ss, default 00:00:00
        Start time in UTC/Zulu (24 hour clock). If None, use default.
        TODO: check for time in date-range date-time object, if that's used for input.
    end_time : HH:mm:ss, default 23:59:59
        End time in UTC/Zulu (24 hour clock). If None, use default.
        TODO: check for time in date-range date-time object, if that's used for input.
    xdateline : boolean, default None
        Keyword argument to enforce spatial inputs that cross the International Date Line.
        Internally, this will translate your longitudes to 0 to 360 to construct the
        correct, valid Shapely geometry.

        WARNING: This will allow your request to be properly submitted and visualized.
        However, this flag WILL NOT automatically correct for incorrectly ordered spatial inputs.

    Examples
    --------
    Initializing Query with a bounding box

    >>> reg_a_bbox = [-55, 68, -48, 71]
    >>> reg_a_dates = ['2019-02-20','2019-02-28']
    >>> reg_a = GenQuery(reg_a_bbox, reg_a_dates)
    >>> print(reg_a)
    Extent type: bounding_box
    Coordinates: [-55.0, 68.0, -48.0, 71.0]
    Date range: (2019-02-20 00:00:00, 2019-02-28 23:59:59)

    Initializing Query with a list of polygon vertex coordinate pairs.

    >>> reg_a_poly = [(-55, 68), (-55, 71), (-48, 71), (-48, 68), (-55, 68)]
    >>> reg_a_dates = ['2019-02-20','2019-02-28']
    >>> reg_a = GenQuery(reg_a_poly, reg_a_dates)
    >>> print(reg_a)
    Extent type: polygon
    Coordinates: [-55.0, 68.0, -55.0, 71.0, -48.0, 71.0, -48.0, 68.0, -55.0, 68.0]
    Date range: (2019-02-20 00:00:00, 2019-02-28 23:59:59)

    Initializing Query with a geospatial polygon file.

    >>> aoi = str(Path('./doc/source/example_notebooks/supporting_files/simple_test_poly.gpkg').resolve())
    >>> reg_a_dates = ['2019-02-22','2019-02-28']
    >>> reg_a = GenQuery(aoi, reg_a_dates)
    >>> print(reg_a)
    Extent type: polygon
    Coordinates: [-55.0, 68.0, -55.0, 71.0, -48.0, 71.0, -48.0, 68.0, -55.0, 68.0]
    Date range: (2019-02-22 00:00:00, 2019-02-28 23:59:59)

    See Also
    --------
    Query
    Quest
    """

    def __init__(
        self,
        spatial_extent=None,
        date_range=None,
        start_time=None,
        end_time=None,
        **kwargs,
    ):
        # validate & init spatial extent
        if "xdateline" in kwargs.keys():
            self._spatial = spat.Spatial(spatial_extent, xdateline=kwargs["xdateline"])
        else:
            self._spatial = spat.Spatial(spatial_extent)

        # valiidate and init temporal constraints
        # TODO: Update this to use Temporal class when completed
        if date_range:
            self._start, self._end = val.temporal(date_range, start_time, end_time)

    def __str__(self):
        str = "Extent type: {0} \nCoordinates: {1}\nDate range: ({2}, {3})".format(
            self._spatial._ext_type,
            self._spatial._spatial_ext,
            self._start,
            self._end,
        )
        return str


# DevGoal: update docs throughout to allow for polygon spatial extent
# Note: add files to docstring once implemented
# DevNote: currently this class is not tested
class Query(GenQuery):
    """
    Query and get ICESat-2 data

    ICESat-2 Data object to query, obtain, and perform basic operations on
    available ICESat-2 data products using temporal and spatial input parameters.
    Allows the easy input and formatting of search parameters to match the
    NASA NSIDC DAAC and (development goal-not yet implemented) conversion to multiple data types.
    Expands the superclass GenQuery.

    See the doc page for GenQuery for details on temporal and spatial input parameters.

    Parameters
    ----------
    product : string
        ICESat-2 data product ID, also known as "short name" (e.g. ATL03).
        Available data products can be found at: https://nsidc.org/data/icesat-2/data-sets
    version : string, default most recent version
        Product version, given as a 3 digit string. If no version is given, the current
        version is used. Example: "004"
    cycles : string or a list of strings, default all available orbital cycles
        Product cycle, given as a 2 digit string. If no cycle is given, all available
        cycles are used. Example: "04"
    tracks : string or a list of strings, default all available reference ground tracks (RGTs)
        Product track, given as a 4 digit string. If no track is given, all available
        reference ground tracks are used. Example: "0594"
    files : string, default None
        A placeholder for future development. Not used for any purposes yet.

    Returns
    -------
    query object

    Examples
    --------
    Initializing Query with a bounding box.

    >>> reg_a_bbox = [-55, 68, -48, 71]
    >>> reg_a_dates = ['2019-02-20','2019-02-28']
    >>> reg_a = Query('ATL06', reg_a_bbox, reg_a_dates)
    >>> print(reg_a)
    Product ATL06 v005
    ('bounding_box', [-55.0, 68.0, -48.0, 71.0])
    Date range ['2019-02-20', '2019-02-28']

    Initializing Query with a list of polygon vertex coordinate pairs.

    >>> reg_a_poly = [(-55, 68), (-55, 71), (-48, 71), (-48, 68), (-55, 68)]
    >>> reg_a_dates = ['2019-02-20','2019-02-28']
    >>> reg_a = Query('ATL06', reg_a_poly, reg_a_dates)
    >>> reg_a.spatial_extent
    ('polygon', [-55.0, 68.0, -55.0, 71.0, -48.0, 71.0, -48.0, 68.0, -55.0, 68.0])

    Initializing Query with a geospatial polygon file.

    >>> aoi = str(Path('./doc/source/example_notebooks/supporting_files/simple_test_poly.gpkg').resolve())
    >>> reg_a_dates = ['2019-02-22','2019-02-28']
    >>> reg_a = Query('ATL06', aoi, reg_a_dates)
    >>> print(reg_a)
    Product ATL06 v005
    ('polygon', [-55.0, 68.0, -55.0, 71.0, -48.0, 71.0, -48.0, 68.0, -55.0, 68.0])
    Date range ['2019-02-22', '2019-02-28']

    See Also
    --------
    GenQuery
    """

    # ----------------------------------------------------------------------
    # Constructors

    def __init__(
        self,
        product=None,
        spatial_extent=None,
        date_range=None,
        start_time=None,
        end_time=None,
        version=None,
        cycles=None,
        tracks=None,
        files=None,  # NOTE: if you end up implemeting this feature here, use a better variable name than "files"
        **kwargs,
    ):

        # Check necessary combination of input has been specified
        if (
            (product is None or spatial_extent is None)
            or (
                (date_range is None and cycles is None and tracks is None)
                and int(product[-2:]) <= 13
            )
            and files is None
        ):
            raise ValueError(
                "Please provide the required inputs. Use help([function]) to view the function's documentation"
            )

        if files is not None:
            self._source = "files"
            # self.file_vars = Variables(self._source)
        else:
            self._source = "order"
            # self.order_vars = Variables(self._source)
        # self.variables = Variables(self._source)

        self._prod = is2ref._validate_product(product)

        super().__init__(spatial_extent, date_range, start_time, end_time, **kwargs)

        self._version = val.prod_version(self.latest_version(), version)

        # build list of available CMR parameters if reducing by cycle or RGT
        # or a list of explicitly named files (full or partial names)
        # DevGoal: add file name search to optional queries
        if cycles or tracks:
            # get lists of available ICESat-2 cycles and tracks
            self._cycles = val.cycles(cycles)
            self._tracks = val.tracks(tracks)
            # create list of CMR parameters for granule name
            self._readable_granule_name = apifmt._fmt_readable_granules(
                self._prod, cycles=self.cycles, tracks=self.tracks
            )

    # ----------------------------------------------------------------------
    # Properties

    def __str__(self):
        str = "Product {2} v{3}\n{0}\nDate range {1}".format(
            self.spatial_extent, self.dates, self.product, self.product_version
        )
        return str

    @property
    def dataset(self):
        """
        Legacy property included to provide depracation warning.

        See Also
        --------
        product
        """
        warnings.filterwarnings("always")
        warnings.warn(
            "In line with most common usage, 'dataset' has been replaced by 'product'.",
            DeprecationWarning,
        )

    @property
    def product(self):
        """
        Return the short name product ID string associated with the query object.

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'])
        >>> reg_a.product
        'ATL06'
        """
        return self._prod

    @property
    def product_version(self):
        """
        Return the product version of the data object.

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'])
        >>> reg_a.product_version
        '005'

        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'], version='1')
        >>> reg_a.product_version
        '001'
        """
        return self._version

    @property
    def spatial(self):
        """
        Return the spatial object, which provides the underlying functionality for validating
        and formatting geospatial objects. The spatial object has several properties to enable
        user access to the stored spatial extent in multiple formats.

        See Also
        --------
        spatial.Spatial.spatial_extent
        spatial.Spatial.extent_type
        spatial.Spatial.extent_file
        spatial.Spatial

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'])
        >>> reg_a.spatial # doctest: +SKIP
        <icepyx.core.spatial.Spatial at [location]>

        >>> print(reg_a.spatial)
        Extent type: bounding_box
        Coordinates: [-55.0, 68.0, -48.0, 71.0]

        """
        return self._spatial

    @property
    def spatial_extent(self):
        """
        Return an array showing the spatial extent of the query object.
        Spatial extent is returned as an input type (which depends on how
        you initially entered your spatial data) followed by the geometry data.
        Bounding box data is [lower-left-longitude, lower-left-latitute, upper-right-longitude, upper-right-latitude].
        Polygon data is [longitude1, latitude1, longitude2, latitude2,
                        ... longitude_n,latitude_n, longitude1,latitude1].

        Returns
        -------
        tuple of length 2
        First tuple element is the spatial type ("bounding box" or "polygon").
        Second tuple element is the spatial extent as a list of coordinates.

        Examples
        --------

        # Note: coordinates returned as float, not int
        >>> reg_a = Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'])
        >>> reg_a.spatial_extent
        ('bounding_box', [-55.0, 68.0, -48.0, 71.0])

        >>> reg_a = Query('ATL06',[(-55, 68), (-55, 71), (-48, 71), (-48, 68), (-55, 68)],['2019-02-20','2019-02-28'])
        >>> reg_a.spatial_extent
        ('polygon', [-55.0, 68.0, -55.0, 71.0, -48.0, 71.0, -48.0, 68.0, -55.0, 68.0])

        # NOTE Is this where we wanted to put the file-based test/example?
        # The test file path is: examples/supporting_files/simple_test_poly.gpkg

        See Also
        --------
        Spatial.extent
        Spatial.extent_type
        Spatial.extent_as_gdf

        """

        return (self._spatial._ext_type, self._spatial._spatial_ext)

    @property
    def dates(self):
        """
        Return an array showing the date range of the query object.
        Dates are returned as an array containing the start and end datetime objects, inclusive, in that order.

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'])
        >>> reg_a.dates
        ['2019-02-20', '2019-02-28']
        """
        if not hasattr(self, "_start"):
            return ["No temporal parameters set"]
        else:
            return [
                self._start.strftime("%Y-%m-%d"),
                self._end.strftime("%Y-%m-%d"),
            ]  # could also use self._start.date()

    @property
    def start_time(self):
        """
        Return the start time specified for the start date.

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'])
        >>> reg_a.start_time
        '00:00:00'

        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'], start_time='12:30:30')
        >>> reg_a.start_time
        '12:30:30'
        """
        if not hasattr(self, "_start"):
            return ["No temporal parameters set"]
        else:
            return self._start.strftime("%H:%M:%S")

    @property
    def end_time(self):
        """
        Return the end time specified for the end date.

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'])
        >>> reg_a.end_time
        '23:59:59'

        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'], end_time='10:20:20')
        >>> reg_a.end_time
        '10:20:20'
        """
        if not hasattr(self, "_end"):
            return ["No temporal parameters set"]
        else:
            return self._end.strftime("%H:%M:%S")

    @property
    def cycles(self):
        """
        Return the unique ICESat-2 orbital cycle.

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'])
        >>> reg_a.cycles
        ['No orbital parameters set']

        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71], cycles=['03','04'], tracks=['0849','0902'])
        >>> reg_a.cycles
        ['03', '04']
        """
        if not hasattr(self, "_cycles"):
            return ["No orbital parameters set"]
        else:
            return sorted(set(self._cycles))

    @property
    def tracks(self):
        """
        Return the unique ICESat-2 Reference Ground Tracks

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'])
        >>> reg_a.tracks
        ['No orbital parameters set']

        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71], cycles=['03','04'], tracks=['0849','0902'])
        >>> reg_a.tracks
        ['0849', '0902']
        """
        if not hasattr(self, "_tracks"):
            return ["No orbital parameters set"]
        else:
            return sorted(set(self._tracks))

    @property
    def CMRparams(self):
        """
        Display the CMR key:value pairs that will be submitted. It generates the dictionary if it does not already exist.

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'])
        >>> reg_a.CMRparams
        {'short_name': 'ATL06',
        'version': '005',
        'temporal': '2019-02-20T00:00:00Z,2019-02-28T23:59:59Z',
        'bounding_box': '-55.0,68.0,-48.0,71.0'}
        """

        if not hasattr(self, "_CMRparams"):
            self._CMRparams = apifmt.Parameters("CMR")
        # print(self._CMRparams)
        # print(self._CMRparams.fmted_keys)

        # dictionary of optional CMR parameters
        kwargs = {}
        # temporal CMR parameters
        if hasattr(self, "_start") and hasattr(self, "_end"):
            kwargs["start"] = self._start
            kwargs["end"] = self._end
        # granule name CMR parameters (orbital or file name)
        # DevGoal: add to file name search to optional queries
        if hasattr(self, "_readable_granule_name"):
            kwargs["options[readable_granule_name][pattern]"] = "true"
            kwargs["options[spatial][or]"] = "true"
            kwargs["readable_granule_name[]"] = self._readable_granule_name

        if self._CMRparams.fmted_keys == {}:
            self._CMRparams.build_params(
                product=self.product,
                version=self._version,
                extent_type=self._spatial._ext_type,
                spatial_extent=self._spatial.fmt_for_CMR(),
                **kwargs,
            )

        return self._CMRparams.fmted_keys

    @property
    def reqparams(self):
        """
        Display the required key:value pairs that will be submitted. It generates the dictionary if it does not already exist.

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'])
        >>> reg_a.reqparams
        {'page_size': 2000}

        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28']) # doctest: +SKIP
        >>> reg_a.earthdata_login() # doctest: +SKIP
        >>> reg_a.order_granules() # doctest: +SKIP
        >>> reg_a.reqparams # doctest: +SKIP
        {'page_size': 2000, 'page_num': 1, 'request_mode': 'async', 'include_meta': 'Y', 'client_string': 'icepyx'}
        """

        if not hasattr(self, "_reqparams"):
            self._reqparams = apifmt.Parameters("required", reqtype="search")
            self._reqparams.build_params()

        return self._reqparams.fmted_keys

    # @property
    # DevQuestion: if I make this a property, I get a "dict" object is not callable when I try to give input kwargs... what approach should I be taking?
    def subsetparams(self, **kwargs):
        """
        Display the subsetting key:value pairs that will be submitted. It generates the dictionary if it does not already exist
        and returns an empty dictionary if subsetting is set to False during ordering.

        Parameters
        ----------
        **kwargs : key-value pairs
            Additional parameters to be passed to the subsetter.
            By default temporal and spatial subset keys are passed.
            Acceptable key values are ['format','projection','projection_parameters','Coverage'].
            At this time (2020-05), only variable ('Coverage') parameters will be automatically formatted.

        See Also
        --------
        order_granules

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'])
        >>> reg_a.subsetparams()
        {'time': '2019-02-20T00:00:00,2019-02-28T23:59:59',
        'bbox': '-55.0,68.0,-48.0,71.0'}
        """
        if not hasattr(self, "_subsetparams"):
            self._subsetparams = apifmt.Parameters("subset")

        # temporal subsetting parameters
        if hasattr(self, "_start") and hasattr(self, "_end"):
            kwargs["start"] = self._start
            kwargs["end"] = self._end

        if self._subsetparams == None and not kwargs:
            return {}
        else:
            if self._subsetparams == None:
                self._subsetparams = apifmt.Parameters("subset")
            if self._spatial._geom_file is not None:
                self._subsetparams.build_params(
                    geom_filepath=self._spatial._geom_file,
                    extent_type=self._spatial._ext_type,
                    spatial_extent=self._spatial.fmt_for_EGI(),
                    **kwargs,
                )
            else:
                self._subsetparams.build_params(
                    extent_type=self._spatial._ext_type,
                    spatial_extent=self._spatial.fmt_for_EGI(),
                    **kwargs,
                )

            return self._subsetparams.fmted_keys

    # DevGoal: add to tests
    # DevGoal: add statements to the following vars properties to let the user know if they've got a mismatched source and vars type
    @property
    def order_vars(self):
        """
        Return the order variables object.
        This instance is generated when data is ordered from the NSIDC.

        See Also
        --------
        variables.Variables

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28']) # doctest: +SKIP
        >>> reg_a.earthdata_login() # doctest: +SKIP
        >>> reg_a.order_vars # doctest: +SKIP
        <icepyx.core.variables.Variables at [location]>
        """

        if not hasattr(self, "_order_vars"):
            if self._source == "order":
                # DevGoal: check for active session here
                if hasattr(self, "_cust_options"):
                    self._order_vars = Variables(
                        self._source,
                        session=self._session,
                        product=self.product,
                        avail=self._cust_options["variables"],
                    )
                else:
                    self._order_vars = Variables(
                        self._source,
                        session=self._session,
                        product=self.product,
                        version=self._version,
                    )

        # I think this is where property setters come in, and one should be used here? Right now order_vars.avail is only filled in
        # if _cust_options exists when the class is initialized, but not if _cust_options is filled in prior to another call to order_vars
        # if self._order_vars.avail == None and hasattr(self, '_cust_options'):
        #     print('got into the loop')
        #     self._order_vars.avail = self._cust_options['variables']

        return self._order_vars

    @property
    def file_vars(self):
        """
        Return the file variables object.
        This instance is generated when files are used to create the data object (not yet implemented).

        See Also
        --------
        variables.Variables

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28']) # doctest: +SKIP
        >>> reg_a.earthdata_login() # doctest: +SKIP
        >>> reg_a.file_vars # doctest: +SKIP
        <icepyx.core.variables.Variables at [location]>
        """

        if not hasattr(self, "_file_vars"):
            if self._source == "file":
                self._file_vars = Variables(self._source, product=self.product)

        return self._file_vars

    @property
    def granules(self):
        """
        Return the granules object, which provides the underlying funtionality for searching, ordering,
        and downloading granules for the specified product. Users are encouraged to use the built in wrappers
        rather than trying to access the granules object themselves.

        See Also
        --------
        avail_granules
        order_granules
        download_granules
        granules.Granules

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28']) # doctest: +SKIP
        >>> reg_a.granules # doctest: +SKIP
        <icepyx.core.granules.Granules at [location]>
        """

        if not hasattr(self, "_granules"):
            self._granules = Granules()
        elif self._granules == None:
            self._granules = Granules()

        return self._granules

    # ----------------------------------------------------------------------
    # Methods - Get and display neatly information at the product level

    def product_summary_info(self):
        """
        Display a summary of selected metadata for the specified version of the product
        of interest (the collection).

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'], version='005')
        >>> reg_a.product_summary_info()
        title :  ATLAS/ICESat-2 L3A Land Ice Height V005
        short_name :  ATL06
        version_id :  005
        time_start :  2018-10-14T00:00:00.000Z
        coordinate_system :  CARTESIAN
        summary :  This data set (ATL06) provides geolocated, land-ice surface heights (above the WGS 84 ellipsoid, ITRF2014 reference frame), plus ancillary parameters that can be used to interpret and assess the quality of the height estimates. The data were acquired by the Advanced Topographic Laser Altimeter System (ATLAS) instrument on board the Ice, Cloud and land Elevation Satellite-2 (ICESat-2) observatory.
        orbit_parameters :  {'swath_width': '36.0', 'period': '96.8', 'inclination_angle': '92.0', 'number_of_orbits': '0.071428571', 'start_circular_latitude': '0.0'}
        """
        if not hasattr(self, "_about_product"):
            self._about_product = is2ref.about_product(self._prod)
        summ_keys = [
            "title",
            "short_name",
            "version_id",
            "time_start",
            "coordinate_system",
            "summary",
            "orbit_parameters",
        ]
        for key in summ_keys:
            print(key, ": ", self._about_product["feed"]["entry"][-1][key])

    def product_all_info(self):
        """
        Display all metadata about the product of interest (the collection).

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28']) # doctest: +SKIP
        >>> reg_a.product_all_info() # doctest: +SKIP
        {very long prettily-formatted dictionary output}

        """
        if not hasattr(self, "_about_product"):
            self._about_product = is2ref.about_product(self._prod)
        pprint.pprint(self._about_product)

    def latest_version(self):
        """
        Determine the most recent version available for the given product.

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'])
        >>> reg_a.latest_version()
        '005'
        """
        if not hasattr(self, "_about_product"):
            self._about_product = is2ref.about_product(self._prod)
        return max(
            [entry["version_id"] for entry in self._about_product["feed"]["entry"]]
        )

    def show_custom_options(self, dictview=False):
        """
        Display customization/subsetting options available for this product.

        Parameters
        ----------
        dictview : boolean, default False
            Show the variable portion of the custom options list as a dictionary with key:value
            pairs representing variable:paths-to-variable rather than as a long list of full
            variable paths.

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28']) # doctest: +SKIP
        >>> reg_a.earthdata_login() # doctest: +SKIP
        >>> reg_a.show_custom_options(dictview=True) # doctest: +SKIP
        Subsetting options
        [{'id': 'ICESAT2',
        'maxGransAsyncRequest': '2000',
        'maxGransSyncRequest': '100',
        'spatialSubsetting': 'true',
        'spatialSubsettingShapefile': 'true',
        'temporalSubsetting': 'true',
        'type': 'both'}]
        Data File Formats (Reformatting Options)
        ['TABULAR_ASCII', 'NetCDF4-CF', 'Shapefile', 'NetCDF-3']
        Reprojection Options
        []
        Data File (Reformatting) Options Supporting Reprojection
        ['TABULAR_ASCII', 'NetCDF4-CF', 'Shapefile', 'NetCDF-3', 'No reformatting']
        Data File (Reformatting) Options NOT Supporting Reprojection
        []
        Data Variables (also Subsettable)
        ['ancillary_data/atlas_sdp_gps_epoch',
        'ancillary_data/control',
        'ancillary_data/data_end_utc',
        .
        .
        .
        'quality_assessment/gt3r/signal_selection_source_fraction_3']
        """
        headers = [
            "Subsetting options",
            "Data File Formats (Reformatting Options)",
            "Reprojection Options",
            "Data File (Reformatting) Options Supporting Reprojection",
            "Data File (Reformatting) Options NOT Supporting Reprojection",
            "Data Variables (also Subsettable)",
        ]
        keys = [
            "options",
            "fileformats",
            "reprojectionONLY",
            "formatreproj",
            "noproj",
            "variables",
        ]

        try:
            all(key in self._cust_options.keys() for key in keys)
        except AttributeError or KeyError:
            self._cust_options = is2ref._get_custom_options(
                self._session, self.product, self._version
            )

        for h, k in zip(headers, keys):
            print(h)
            if k == "variables" and dictview:
                vgrp, paths = Variables.parse_var_list(self._cust_options[k])
                pprint.pprint(vgrp)
            else:
                pprint.pprint(self._cust_options[k])

    # ----------------------------------------------------------------------
    # Methods - Login and Granules (NSIDC-API)

    def earthdata_login(self, uid=None, email=None, s3token=False, **kwargs) -> None:
        """
        Authenticate with NASA Earthdata to enable data ordering and download.

        Generates the needed authentication sessions and tokens, including for cloud access.
        Authentication is completed using the [earthaccess library](https://nsidc.github.io/earthaccess/).
        Methods for authenticating are:
            1. Storing credentials as environment variables ($EARTHDATA_LOGIN and $EARTHDATA_PASSWORD)
            2. Entering credentials interactively
            3. Storing credentials in a .netrc file (not recommended for security reasons)
        More details on using these methods is available in the [earthaccess documentation](https://nsidc.github.io/earthaccess/tutorials/restricted-datasets/#auth).
        The input parameters listed here are provided for backwards compatibility;
        before earthaccess existed, icepyx handled authentication and required these inputs.

        Parameters
        ----------
        uid : string, default None
            Deprecated keyword for Earthdata login user ID.
        email : string, default None
            Deprecated keyword for backwards compatibility.
        s3token : boolean, default False
            Deprecated keyword to generate AWS s3 ICESat-2 data access credentials
        kwargs : key:value pairs
            Keyword arguments to be passed into earthaccess.login().

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28']) # doctest: +SKIP
        >>> reg_a.earthdata_login() # doctest: +SKIP
        Enter your Earthdata Login username: ___________________

        EARTHDATA_USERNAME and EARTHDATA_PASSWORD are not set in the current environment, try setting them or use a different strategy (netrc, interactive)
        No .netrc found in /Users/username

        """

        auth = earthaccess.login(**kwargs)
        if auth.authenticated:
            self._auth = auth
            self._session = auth.get_session()

        if s3token == True:
            self._s3login_credentials = auth.get_s3_credentials(daac="NSIDC")

        if uid != None or email != None:
            warnings.warn(
                "The user id (uid) and/or email keyword arguments are no longer required.",
                DeprecationWarning,
            )

    # DevGoal: check to make sure the see also bits of the docstrings work properly in RTD
    def avail_granules(self, ids=False, cycles=False, tracks=False, cloud=False):
        """
        Obtain information about the available granules for the query
        object's parameters. By default, a complete list of available granules is
        obtained and stored in the object, but only summary information is returned.
        Lists of granule IDs, cycles and RGTs can be obtained using the boolean triggers.

        Parameters
        ----------
        ids : boolean, default False
            Indicates whether the function should return a list of granule IDs.

        cycles : boolean, default False
            Indicates whether the function should return a list of orbital cycles.

        tracks : boolean, default False
            Indicates whether the function should return a list of RGTs.

        cloud : boolean, default False
            Indicates whether the function should return data available in the cloud.
            Note: except in rare cases while data is in the process of being appended to,
            data available in the cloud and for download via on-premesis will be identical.

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28'])
        >>> reg_a.avail_granules()
        {'Number of available granules': 4,
        'Average size of granules (MB)': 53.948360681525,
        'Total size of all granules (MB)': 215.7934427261}

        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-23'])
        >>> reg_a.avail_granules(ids=True)
        [['ATL06_20190221121851_08410203_005_01.h5', 'ATL06_20190222010344_08490205_005_01.h5']]
        >>> reg_a.avail_granules(cycles=True)
        [['02', '02']]
        >>> reg_a.avail_granules(tracks=True)
        [['0841', '0849']]
        """

        #         REFACTOR: add test to make sure there's a session
        if not hasattr(self, "_granules"):
            self.granules
        try:
            self.granules.avail
        except AttributeError:
            self.granules.get_avail(self.CMRparams, self.reqparams, cloud=cloud)

        if ids or cycles or tracks or cloud:
            # list of outputs in order of ids, cycles, tracks, cloud
            return granules.gran_IDs(
                self.granules.avail,
                ids=ids,
                cycles=cycles,
                tracks=tracks,
                cloud=cloud,
            )
        else:
            return granules.info(self.granules.avail)

    # DevGoal: display output to indicate number of granules successfully ordered (and number of errors)
    # DevGoal: deal with subset=True for variables now, and make sure that if a variable subset
    # Coverage kwarg is input it's successfully passed through all other functions even if this is the only one run.
    def order_granules(self, verbose=False, subset=True, email=False, **kwargs):
        """
        Place an order for the available granules for the query object.

        Parameters
        ----------
        verbose : boolean, default False
            Print out all feedback available from the order process.
            Progress information is automatically printed regardless of the value of verbose.
        subset : boolean, default True
            Apply subsetting to the data order from the NSIDC, returning only data that meets the
            subset parameters. Spatial and temporal subsetting based on the input parameters happens
            by default when subset=True, but additional subsetting options are available.
            Spatial subsetting returns all data that are within the area of interest (but not complete
            granules. This eliminates false-positive granules returned by the metadata-level search)
        email: boolean, default False
            Have NSIDC auto-send order status email updates to indicate order status as pending/completed.
            The emails are sent to the account associated with your Earthdata account.
        **kwargs : key-value pairs
            Additional parameters to be passed to the subsetter.
            By default temporal and spatial subset keys are passed.
            Acceptable key values are ['format','projection','projection_parameters','Coverage'].
            The variable 'Coverage' list should be constructed using the `order_vars.wanted` attribute of the object.
            At this time (2020-05), only variable ('Coverage') parameters will be automatically formatted.

        See Also
        --------
        granules.place_order

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28']) # doctest: +SKIP
        >>> reg_a.earthdata_login() # doctest: +SKIP
        >>> reg_a.order_granules() # doctest: +SKIP
        order ID: [###############]
        [order status output]
        error messages:
        [if any were returned from the NSIDC subsetter, e.g. No data found that matched subset constraints.]
        .
        .
        .
        Retry request status is: complete
        """

        if not hasattr(self, "reqparams"):
            self.reqparams

        if self._reqparams._reqtype == "search":
            self._reqparams._reqtype = "download"

        if "email" in self._reqparams.fmted_keys.keys() or email == False:
            self._reqparams.build_params(**self._reqparams.fmted_keys)
        elif email == True:
            user_profile = self._auth.get_user_profile()
            self._reqparams.build_params(
                **self._reqparams.fmted_keys, email=user_profile["email_address"]
            )

        if subset is False:
            self._subsetparams = None
        elif (
            subset == True
            and hasattr(self, "_subsetparams")
            and self._subsetparams == None
        ):
            del self._subsetparams

        # REFACTOR: add checks here to see if the granules object has been created,
        # and also if it already has a list of avail granules (if not, need to create one and add session)
        if not hasattr(self, "_granules"):
            self.granules

        # Place multiple orders, one per granule, if readable_granule_name is used.
        if "readable_granule_name[]" in self.CMRparams.keys():
            gran_name_list = self.CMRparams["readable_granule_name[]"]
            tempCMRparams = self.CMRparams
            if len(gran_name_list) > 1:
                print(
                    "NSIDC only allows ordering of one granule by name at a time; your orders will be placed accordingly."
                )
            for gran in gran_name_list:
                tempCMRparams.update({"readable_granule_name[]": gran})
                self._granules.place_order(
                    tempCMRparams,
                    self.reqparams,
                    self.subsetparams(**kwargs),
                    verbose,
                    subset,
                    session=self._session,
                    geom_filepath=self._spatial._geom_file,
                )

        else:
            self._granules.place_order(
                self.CMRparams,
                self.reqparams,
                self.subsetparams(**kwargs),
                verbose,
                subset,
                session=self._session,
                geom_filepath=self._spatial._geom_file,
            )

    # DevGoal: put back in the kwargs here so that people can just call download granules with subset=False!
    def download_granules(
        self, path, verbose=False, subset=True, restart=False, **kwargs
    ):  # , extract=False):
        """
        Downloads the data ordered using order_granules.

        Parameters
        ----------
        path : string
            String with complete path to desired download location.
        verbose : boolean, default False
            Print out all feedback available from the order process.
            Progress information is automatically printed regardless of the value of verbose.
        subset : boolean, default True
            Apply subsetting to the data order from the NSIDC, returning only data that meets the
            subset parameters. Spatial and temporal subsetting based on the input parameters happens
            by default when subset=True, but additional subsetting options are available.
            Spatial subsetting returns all data that are within the area of interest (but not complete
            granules. This eliminates false-positive granules returned by the metadata-level search)
        restart : boolean, default false
            If previous download was terminated unexpectedly. Run again with restart set to True to continue.
        **kwargs : key-value pairs
            Additional parameters to be passed to the subsetter.
            By default temporal and spatial subset keys are passed.
            Acceptable key values are ['format','projection','projection_parameters','Coverage'].
            The variable 'Coverage' list should be constructed using the `order_vars.wanted` attribute of the object.
            At this time (2020-05), only variable ('Coverage') parameters will be automatically formatted.

        See Also
        --------
        granules.download
        """
        """
        extract : boolean, default False
            Unzip the downloaded granules.

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06',[-55, 68, -48, 71],['2019-02-20','2019-02-28']) # doctest: +SKIP
        >>> reg_a.earthdata_login() # doctest: +SKIP
        >>> reg_a.download_granules('/path/to/download/folder') # doctest: +SKIP
        Beginning download of zipped output...
        Data request [##########] of x order(s) is complete.
        """

        # if not os.path.exists(path):
        #     os.mkdir(path)
        # os.chdir(path)

        if not hasattr(self, "_granules"):
            self.granules

        if restart == True:
            pass
        else:
            if (
                not hasattr(self._granules, "orderIDs")
                or len(self._granules.orderIDs) == 0
            ):
                self.order_granules(verbose=verbose, subset=subset, **kwargs)

        self._granules.download(verbose, path, session=self._session, restart=restart)

    # DevGoal: add testing? What do we test, and how, given this is a visualization.
    # DevGoal(long term): modify this to accept additional inputs, etc.
    # DevGoal: move this to it's own module for visualizing, etc.
    # DevGoal: see Amy's data access notebook for a zoomed in map - implement here?
    def visualize_spatial_extent(
        self,
    ):  # additional args, basemap, zoom level, cmap, export
        """
        Creates a map displaying the input spatial extent

        Examples
        --------
        >>> reg_a = ipx.Query('ATL06','path/spatialfile.shp',['2019-02-22','2019-02-28']) # doctest: +SKIP
        >>> reg_a.visualize_spatial_extent # doctest: +SKIP
        [visual map output]
        """

        gdf = self._spatial.extent_as_gdf

        try:
            from shapely.geometry import Polygon
            import geoviews as gv

            gv.extension("bokeh")

            bbox_poly = gv.Path(gdf["geometry"]).opts(color="red", line_color="red")
            tile = gv.tile_sources.EsriImagery.opts(width=500, height=500)
            return tile * bbox_poly

        except ImportError:
            world = gpd.read_file(gpd.datasets.get_path("naturalearth_lowres"))
            f, ax = plt.subplots(1, figsize=(12, 6))
            world.plot(ax=ax, facecolor="lightgray", edgecolor="gray")
            gdf.plot(ax=ax, color="#FF8C00", alpha=0.7)
            plt.show()

    def visualize_elevation(self):
        """
        Visualize elevation requested from OpenAltimetry API using datashader based on cycles
        https://holoviz.org/tutorial/Large_Data.html

        Returns
        -------
        map_cycle, map_rgt + lineplot_rgt : Holoviews objects
            Holoviews data visualization elements
        """
        viz = Visualize(self)
        cycle_map, rgt_map = viz.viz_elevation()

        return cycle_map, rgt_map
