#!/usr/bin/env python3

# ----------------------------------------------------------------------------
# Copyright (c) 2020--, Qiyun Zhu.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file LICENSE, distributed with this software.
# ----------------------------------------------------------------------------

"""Functions for handling input and output files.
"""

from os import listdir
from os.path import basename, dirname, splitext, isfile, join
import gzip
import bz2
import lzma

from .util import allkeys, feat_n_cnt
from .tree import lineage_str


ZIPDIC = {'.gz': gzip, '.gzip': gzip,
          '.bz2': bz2, '.bzip2': bz2,
          '.xz': lzma, '.lz': lzma, '.lzma': lzma}


def openzip(fp, mode='rt'):
    """Open a regular or compressed file by matching filename extension to
    proper library.

    Parameters
    ----------
    fp : str
        Input filepath.
    mode : str, optional
        Python file mode. Default: "rt" (read as text).

    Returns
    -------
    file handle
        Text stream ready to be read.
    """
    ext = splitext(fp)[1]
    zipfunc = getattr(ZIPDIC[ext], 'open') if ext in ZIPDIC else open
    return zipfunc(fp, mode)


def file2stem(fname, ext=None):
    """Extract stem from filename.

    Parameters
    ----------
    fp : str
        Filepath.
    ext : str, optional
        Filename extension.

    Returns
    -------
    str
        Filename stem.

    Notes
    -----
    Common compression file extensions are recognized and stripped beforehand.

    There is no commonly accepted term for "filename with extension stripped".
    The term "stem" is from C++. In Python's `splitext` function, it is called
    "root". But "root" in this program describes tree root.
    """
    if ext is not None:
        if not fname.endswith(ext):
            raise ValueError('Filepath and filename extension do not match.')
        return fname[:-len(ext)]
    else:
        stem, ext = splitext(fname)
        if ext in ZIPDIC:
            stem, ext = splitext(stem)
        return stem


def path2stem(fp, ext=None):
    """Get filename stem from filepath.

    Parameters
    ----------
    fp : str
        Filepath.
    ext : str, optional
        Filename extension.

    Returns
    -------
    str
        Filename stem.
    """
    return file2stem(basename(fp), ext)


def read_ids(fh):
    """Read a list of IDs from a file.

    Parameters
    ----------
    fh : iterable of str
        ID list.

    Returns
    -------
    list of str
        ID list.

    Notes
    -----
    Only the first column before <tab> is considered. Lines starting with "#"
    are omitted. Empty entries are discarded.
    """
    if fh is None:
        return
    res = []
    for line in fh:
        if not line.startswith('#'):
            id_ = line.strip().partition('\t')[0]
            if id_:
                res.append(id_)
    if not res:
        raise ValueError('No ID is read.')
    if len(set(res)) < len(res):
        raise ValueError('Duplicate IDs found.')
    return res


def id2file_from_dir(dir_, ext=None, ids=None):
    """Generate an ID-to-file map from a directory.

    Parameters
    ----------
    dir_ : str
        Directory containing files.
    ext : str, optional
        Filename extension.
    ids : iterable of str, optional
        ID list.

    Returns
    -------
    dict
        ID-to-file map.

    Raises
    ------
    ValueError
        Multiple files have the same stem filename.

    Notes
    -----
    Only top-level directory is searched. Only files but not subdirectories are
    considered.
    """
    res = {}
    for fname in listdir(dir_):
        if isfile(join(dir_, fname)):
            try:
                id_ = file2stem(fname, ext)
            except ValueError:
                continue
            if ids and id_ not in ids:
                continue
            if id_ in res:
                raise ValueError(f'Ambiguous files for ID: "{id_}".')
            res[id_] = fname
    return res


def id2file_from_map(fp):
    """Read ID-to-file mapping from a file.

    Parameters
    ----------
    fp : str
        Path to an ID-to-file mapping file (format: ID <tab> filepath).

    Returns
    -------
    list of tuple, or None
        Ordered ID-to-file map, or None if not a valid mapping file.

    Raises
    ------
    ValueError
        If any of 2nd to nth filepaths does not exist.

    Notes
    -----
    This function checks every line of a file, except for empty lines and lines
    starting with "#", to see if it suffices the format of sample ID <tab>
    filepath.

    The filepath must point to an existing file. The function first checks the
    filepath as absolute, or relative to the current directory. If not found,
    it then searches the same directory as the mapping file. Therefore, instead
    of specifying full paths, one could also provide just filenames as long as
    the mapping file and the alignment files are in the same directory.

    If the filepath in the first line does not exist, the function will return
    None, assuming this is not a mapping file. However if the first filepath
    exists whereas any of the filepaths below does not exist, an error will be
    raised, reminding user of the potentially incorrect filepath.
    """
    res = []
    fdir = dirname(fp)
    with openzip(fp) as fh:
        for line in fh:
            line = line.rstrip()

            # skip empty or commented lines
            if not line or line.startswith('#'):
                continue

            # a valid map must have exactly two columns per line
            try:
                id_, file_ = line.split('\t')
            except ValueError:
                return

            # check full filepath
            if isfile(file_):
                res.append((id_, file_))
                continue

            # search same directory
            fp = join(fdir, file_)
            if isfile(fp):
                res.append((id_, fp))
                continue

            # if previous lines appear to be valid files, raise error
            if res:
                raise ValueError(f'Alignment file "{file_}" does not exist.')

            # otherwise (i.e., this is the first line), return
            return
    return res or None


def read_map(fh, sep='\t', multi=None, count=False):
    """Read a mapping file.

    Parameters
    ----------
    fh : file handle
        Mapping file.
    sep : str, optional
        Separator between columns.
    multi : bool, optional
        Whether one key can correspond to multiple values.
        - True: all values are parsed.
        - False: only first value is parsed.
        - None: skip if there are multiple values.
    count : bool, optional
        Values have counts after colon.

    Yields
    ------
    tuple
        Pair of key and value(s).

    Notes
    -----
    A mapping file is a tab-delimited file (tab can be replaced by a custom
    separator), where the first column is the key, and the remaining columns
    are values.

    In default mode, lines with only one or more than two columns are omitted.
    With multi = False, only the 2nd column is parsed regardless of others.
    With multi = True, 2nd to last columns are all parsed and combined in a
    tuple.

    Counts are numeric suffixes post a colon in a value. With count = True, a
    "value:count" string will be converted into a tuple of (value, count). If
    not applicable, the result will be a tuple of (value, 1).

    This function is among the bottlenecking steps of the pipeline. Performance
    is a major consideration.

    See Also
    --------
    util.feat_n_cnt
    """
    for line in fh:
        row = line.rstrip().split(sep)
        n = len(row)
        if n == 1:
            continue
        key = row[0]

        # first value only
        if not multi:
            if n > 2 and multi is None:
                continue
            value = row[1]
            if count:
                value = feat_n_cnt(value)
            yield key, value

        # all values
        else:
            values = row[1:]
            if count:
                values = (feat_n_cnt(x) for x in values)
            yield key, (*values,)


def write_readmap(fh, rmap, namedic=None):
    """Write a read map to a tab-delimited file.

    Parameters
    ----------
    fh : file handle
        Output file.
    rmap : dict
        Read-to-taxon(a) map.
    namedic : dict, optional
        Taxon name dictionary.
    """
    # sort subjects by count (high-to-low) then by alphabet
    def sortkey(x): return -x[1], x[0]
    for read, taxa in rmap.items():
        row = [read]
        if isinstance(taxa, dict):
            for taxon, count in sorted(taxa.items(), key=sortkey):
                if namedic and taxon in namedic:
                    taxon = namedic[taxon]
                row.append(taxon + ':' + str(count))
        elif namedic and taxa in namedic:
            row.append(namedic[taxa])
        else:
            row.append(taxa)
        print('\t'.join(row), file=fh)


def write_table(fh, data, samples=None, tree=None, rankdic=None, namedic=None,
                name_as_id=False):
    """Write a profile to a tab-delimited file.

    Parameters
    ----------
    fh : file handle
        Output file.
    data : dict
        Profile data.
    samples : list, optional
        Ordered sample ID list.
    tree : dict, optional
        Taxonomic tree, to inform "Lineage" column.
    rankdic : dict, optional
        Rank dictionary, to inform "Rank" column.
    namedic : dict, optional
        Taxon name dictionary, to inform "Name" column.
    name_as_id : bool, optional
        Replace feature IDs with names. It applies to row headers and "Lineage"
        column, and removes "Name" column.

    Returns
    -------
    int
        Number of samples in the table.
    int
        Number of features in the table.

    Notes
    -----
    The output table will have columns as samples and rows as features.
    Optionally, three metadata columns, "Name", "Rank" and "Lineage" will be
    appended to the right of the table.
    """
    if samples:
        samples = [x for x in samples if x in data]
    else:
        samples = sorted(data)

    # table header
    header = ['#FeatureID'] + samples
    if namedic and not name_as_id:
        header.append('Name')
    if rankdic:
        header.append('Rank')
    if tree:
        header.append('Lineage')
    print('\t'.join(header), file=fh)

    # table body
    nrow = 0
    for key in sorted(allkeys(data)):
        # stratification
        stratum, feature = key if isinstance(key, tuple) else (None, key)
        # get feature name
        name = namedic[feature] if namedic and feature in namedic else None
        # fill row header (feature Id or name)
        head = name if name_as_id and name else feature
        row = [f'{stratum}|{head}'] if stratum else [head]
        # fill cell values (feature counts)
        for sample in samples:
            row.append(str(data[sample][key]) if key in data[sample] else '0')
        # fill name column
        if namedic and not name_as_id:
            row.append(name or '')
        # fill rank column
        if rankdic:
            row.append(rankdic[feature] if feature in rankdic else '')
        # fill lineage column
        if tree:
            row.append(lineage_str(
                feature, tree, namedic if name_as_id else None))
        # print row
        print('\t'.join(row), file=fh)
        nrow += 1

    return len(samples), nrow


def prep_table(profile, samples=None, tree=None, rankdic=None, namedic=None,
               name_as_id=False):
    """Convert a profile into data, index and columns, as well as metadata if
    applicable, which can be further converted into a TSV file, BIOM table or
    Pandas DataFrame.

    Parameters
    ----------
    profile : dict
        Profile data.
    samples : list, optional
        Ordered sample ID list.
    tree : dict, optional
        Taxonomic tree, to inform "Lineage" column.
    rankdic : dict, optional
        Rank dictionary, to inform "Rank" column.
    namedic : dict, optional
        Taxon name dictionary, to inform "Name" column.
    name_as_id : bool, optional
        Replace feature IDs with names. It applies to row headers and "Lineage"
        column, and removes "Name" column.

    Returns
    -------
    list of list
        Data (2D array of values).
    list
        Features (rows, Pandas index, or BIOM observation IDs).
    list
        Samples (columns, Pandas columns, or BIOM sample IDs).
    list of dict
        Metadata (extra columns, or BIOM observation metadata).

    Examples
    --------
    Convert output to a BIOM table:
    >>> import biom
    >>> args = profile, samples, tree, rankdic, namedic, name_as_id
    >>> table = biom.Table(prep_table(*args))

    Convert output to a Pandas DataFrame (data only):
    >>> import pandas as pd
    >>> data, features, samples, metadata = prep_table(*args)
    >>> df = pd.DataFrame(data, features, samples)

    Convert output to a Pandas DataFrame (data and metadata):
    >>> df = pd.concat([pd.DataFrame(data, features, samples),
                        pd.DataFrame.from_records(metadata, features)], axis=1)

    See Also
    --------

    Notes
    -----
    Optionally, three metadata columns, "Name", "Rank" and "Lineage" will be
    appended to the table.

    A feature will be dropped if all its values are zero. However, samples will
    not be dropped even when empty.

    A stratified feature will be printed as "stratum|feature".
    """
    # determine range and order of samples
    samples = [x for x in samples if x in profile] if samples else sorted(
        profile)

    # determine metadata columns
    namecol = namedic and not name_as_id or None
    metacols = tuple(filter(None, (
        namecol and 'Name', rankdic and 'Rank', tree and 'Lineage')))

    notnone = None.__ne__
    features, data, metadata = [], [], []

    # sort features in alphabetical order
    for key in sorted(allkeys(profile)):

        # determine cell values (feature counts)
        datum = [profile[x][key] if key in profile[x] else 0 for x in samples]
        if not any(datum):
            continue
        data.append(datum)

        # determine feature Id
        stratum, taxon = key if isinstance(key, tuple) else (None, key)
        name = namedic[taxon] if namedic and taxon in namedic else None
        feature = name if name_as_id and name else taxon
        feature = f'{stratum}|{feature}' if stratum else feature
        features.append(feature)

        # determine metadata
        metadatum = dict(zip(metacols, filter(notnone, (
            namecol and (name or ''),
            rankdic and (rankdic[taxon] if taxon in rankdic else ''),
            tree and lineage_str(
                taxon, tree, namedic if name_as_id else None)))))
        metadata.append(metadatum)

    return data, features, samples, metadata
