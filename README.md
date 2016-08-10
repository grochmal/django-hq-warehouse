README for django-hq-warehouse

## Introduction

Django app for constructing and maintaining the warehouse database in the Hotel
Quickly example Warehouse.

It contains two command line tools:

*   `hqw-checkout-batch`: Loads a single batch from the staging area and
    attempt to upload the rows into the warehouse.  Each row is checked for
errors and only correct rows (or at least rows with statistical value) are
committed to the warehouse database.

*   `hqw-checkout-table`: Attempts to load all rows from a single table in the
    staging area that were marked as errors (ignoring the ones marked for
ignore).  This is meant to be run after errors are corrected in the staging
area.

The usage for both commands look as follows:

    hqw-checkout-batch [-hv] -b <batch number>

      -h  Print usage.
      -v  Be verbose, print successes as well as errors.
      -b  The batch number in the staging area to attempt to fetch for the
          warehouse, it must be a valid batch number (must exist)

    ------

    hqw-checkout-table [-hv] -t <table>

      -h  Print usage.
      -v  Be verbose, print successes as well as errors.
      -t  A table that may contain error rows in the staging area, it uses the
          warehouse naming convention: either `currency`, `forex` or `offer`.

## Loading into the warehouse

The commands from the staging area produce batch numbers which you then should
use with `hqw-checkout-batch`, for example:

    hqw-checkout-batch -v -b 3

This will load all records in the batch that can be uploaded to the warehouse.
Rows that cannot be uploaded because of messy data are not loaded and are
marked as erroneous in the staging area database.  Once the erroneous rows are
corrected you can reload the `bacth` (record previously loaded will be ignored)
or, preferably, reload only the erroneous rows table-by-table with
`hqw-checkout-table`.  For example:

    hqw-checkout-table -v -t offer

## Copying

Copyright (C) 2016 Michal Grochmal

This file is part of `django-hq-warehouse`.

`django-hq-warehouse` is free software; you can redistribute and/or modify all
or parts of it under the terms of the GNU General Public License as published
by the Free Software Foundation; either version 3 of the License, or (at your
option) any later version.

`django-hq-warehouse` is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
details.

The COPYING file contains a copy of the GNU General Public License.  If you
cannot find this file, see <http://www.gnu.org/licenses/>.

