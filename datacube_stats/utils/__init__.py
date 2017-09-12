"""
Useful utilities used in Stats
"""
from __future__ import print_function
import itertools

import numpy as np
import xarray

from datacube.storage.masking import mask_invalid_data, create_mask_value


def tile_iter(tile, chunk_size):
    """
    Return the sequence of chunks to split a tile into computable regions.

    :param Tile tile: a tile of `.shape` size containing `.dim` dimensions
    :param chunk_size: dict of dimension sizes
    :return: Sequence of chunks to iterate across the entire tile
    """
    defaults = tuple(size if dim in chunk_size else None
                     for dim, size in zip(tile.dims, tile.shape))
    steps = _tuplify(tile.dims, chunk_size, defaults)
    return _block_iter(steps, tile.shape)


def _tuplify(keys, values, defaults):
    assert not set(values.keys()) - set(keys), 'bad keys'
    return tuple(values.get(key, default) for key, default in zip(keys, defaults))


def _block_iter(steps, shape):
    return itertools.product(*(_slicify(step, size) for step, size in zip(steps, shape)))


def _slicify(step, size):
    if step is None:
        return [slice(None)]
    else:
        return (slice(i, min(i + step, size)) for i in range(0, size, step))


def sensible_mask_invalid_data(data):
    # TODO This should be pushed up to datacube-core
    # xarray.DataArray.where() converts ints to floats, since NaNs are used to represent nodata
    # by default, this uses float64, which is way over the top for an int16 value, so
    # lets convert to float32 first, to save a bunch of memory.
    data = _convert_to_floats(data)  # This is stripping out variable attributes
    return mask_invalid_data(data)


def sensible_where(data, mask):
    data = _convert_to_floats(data)  # This is stripping out variable attributes
    return data.where(mask)


def da_is_float(da):
    """
    Check if DataArray is of floating point type
    """
    assert hasattr(da, 'dtype')

    return da.dtype.kind is 'f'


def ds_all_float(ds):
    """
    Check if dataset contains only floating point arrays
    """
    assert isinstance(ds, xarray.Dataset)

    for da in ds.data_vars.values():
        if not da_is_float(da):
            return False
    return True


def _convert_to_floats(data):
    assert isinstance(data, xarray.Dataset)

    if ds_all_float(data):
        return data

    def to_float(da):
        if da_is_float(da):
            return da

        out = da.astype(np.float32)

        nodata = getattr(da, 'nodata', None)
        if nodata is None:
            return out

        return out.where(da != nodata)

    return data.apply(to_float, keep_attrs=True)


def cast_back(data, measurements):
    """
    Cast calculated statistic `Dataset` into intended data types.
    When going through intermediate representation as floats,
    restore `nodata` values in place of `NaN`s.
    """
    assert isinstance(data, xarray.Dataset)
    measurements = {measurement['name']: measurement
                    for measurement in measurements}

    data_vars = [name for name in data.data_vars]
    assert set(data_vars) == set(measurements.keys())

    def cast(da):
        """ Cast `DataArray` into intended type. """
        output_measurement = measurements[da.name]
        expected_dtype = np.dtype(output_measurement['dtype'])
        actual_dtype = da.dtype

        if actual_dtype.kind != 'f' or 'nodata' not in output_measurement:
            # did not go through intermediate representation
            # or nodata is unspecified
            if expected_dtype == actual_dtype:
                return da
            else:
                return da.astype(expected_dtype)

        # replace NaNs with nodata
        nans = np.isnan(da.values)
        clone = da.astype(expected_dtype)
        clone.values[nans] = output_measurement['nodata']
        return clone

    return data.apply(cast, keep_attrs=True)


wofs_flag_defs = {'cloud': {'bits': 6, 'description': 'Cloudy', 'values': {0: False, 1: True}},
                  'cloud_shadow': {'bits': 5,
                                   'description': 'Cloud shadow',
                                   'values': {0: False, 1: True}},
                  'dry': {'bits': [7, 6, 5, 4, 3, 1, 0],
                          'description': 'No water detected',
                          'values': {0: True}},
                  'high_slope': {'bits': 4,
                                 'description': 'High slope',
                                 'values': {0: False, 1: True}},
                  'nodata': {'bits': 0, 'description': 'No data', 'values': {1: True}},
                  'noncontiguous': {'bits': 1,
                                    'description': 'At least one EO band is missing over over/undersaturated',
                                    'values': {0: False, 1: True}},
                  'sea': {'bits': 2, 'description': 'Sea', 'values': {0: False, 1: True}},
                  'terrain_or_low_angle': {'bits': 3,
                                           'description': 'terrain shadow or low solar angle',
                                           'values': {0: False, 1: True}},
                  'wet': {'bits': [7, 6, 5, 4, 3, 1, 0],
                          'description': 'Clear and Wet',
                          'values': {128: True}}}


def make_numpy_mask(defn):
    def numpy_mask(variable, **flags):
        """
        :rtype: ndarray
        """
        mask, mask_value = create_mask_value(defn, **flags)

        return variable & mask == mask_value

    return numpy_mask


wofs_mask = make_numpy_mask(wofs_flag_defs)


def wofs_fuser(dest, src):
    valid = wofs_mask(src, noncontiguous=False)

    np.copyto(dest, src, where=valid)

    invalid = (wofs_mask(dest, wet=True) & wofs_mask(src, dry=True)) | (
        wofs_mask(src, wet=True) & wofs_mask(dest, dry=True))
    np.copyto(dest, 2, where=invalid)
    return dest


def tile_to_list(tile):
    """
    Extract tile sources xarray into a list of tuples of datasets
    """
    return [a.item() for a in tile.sources]


def tile_flatten_sources(tile):
    """
    Extract sources from tile as a flat list of Dataset objects,
    this removes any grouping that might have been applied to tile sources
    """
    from functools import reduce
    return reduce(list.__add__, [list(a.item()) for a in tile.sources])


def report_unmatched_datasets(co_unmatched, logger=None):
    """ Printout in "human" format unmatched datasets

    co_unmatched -- dict (int,int) => Tile
    logger -- function that logs string, by default will print to stdout

    returns number of datasets that were skipped
    """
    def default_logger(s):
        print(s)

    logger = default_logger if logger is None else logger
    n = 0

    for cell_idx, tile in co_unmatched.items():
        dss = tile_flatten_sources(tile)

        if len(dss) == 0:
            continue

        n += len(dss)

        logger('Skipping files in tile {},{}'.format(*cell_idx))

        for ds in dss:
            logger(' {} {}'.format(ds.id, ds.local_path))

    return n
