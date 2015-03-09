# Author: Pauli Virtanen <pav@iki.fi>, 2006.
# All rights reserved. See LICENSE.txt.
r"""
colnew
======

Solve multi-point boundary value problems for ODEs

- `solve`: Solve linear and non-linear problems
- `Solution`: Returned by `solve` to represent the solution
- `check_jacobians`: Check ``dfsub`` and ``dgsub`` for correctness

.. seealso:: `scikits.bvp1lg.examples`

Description
-----------

This module uses a modified version of COLNEW [CN]_, a mature solver for
multi-point boundary value problems for ODEs.

COLNEW handles only problems with separated boundary conditions.
Non-separated problems can be converted to separated form for example
by adding dummy variables:

.. math::

    u''(x) = f(x, u)

    u(0) + u(1) = 1

    u(0) u(1) = 2

can be transformed to

.. math::

    u''(x) = f(x, u)

    v'(x) = 0

    v(0) - u(0) = 0

    v(1) + u(1) = 1

    v(1) u(1) = 2

Similarly, problems with constant parameters

.. math::

    u''(x) + (a + 2 \cos(2 x)) u(x) = 0

    u'(0) = 0, u(0) = 1, u'(\pi) = 0

can be transformed to

.. math::

    u''(x) + (a(x) + 2 \cos(2 x)) u(x) = 0

    a'(x) = 0

    u'(0) = 0, u(0) = 1, u'(\pi) = 0

This may make the problem non-linear.

References
----------

.. [CN] U. Ascher and G. Bader (and J. Christiansen and R. D. Russell).
        SIAM J. Sci. Comput. 8, 483 (1987).
        http://www.netlib.org/ode/colnew.f

Module contents
---------------
"""
from __future__ import absolute_import, division, print_function

import numpy as np
from . import _colnew
from . import jacobian as _jacobian
from . import error as _error
from . import complex_adapter as _complex_adapter

## Solution

class Solution(object):
    """
    A solution to a boundary value problem for an ODE
    """
    def __init__(self, ispace, fspace):
        """Initialize the solution from data generated by COLNEW"""
        self.ncomp = ispace[2]
        self.mstar = ispace[3]
        self.nmesh = ispace[0] + 1
        self.ispace = ispace[:(7 + self.ncomp)].copy()
        """The ISPACE vector provided by COLNEW"""
        self.fspace = fspace[:ispace[6]].copy()
        """The FSPACE vector provided by COLNEW"""

    def __call__(self, x):
        """Evaluate the solution at given points.

        Returns
        -------
        sol : ndarray
            The solution vector, as::

                [u_1(x), u_1'(x), ..., u_1^{m_1 - 1}(x), u_2(x), ...
                 u_{ncomp}^{m_{ncomp} - 1}]

            broadcast to ``x``. Shape of the returned array
            is x.shape + (mstar,).
        """
        x = np.asarray(x)
        y = _colnew.appsln_many(x.flat, self.fspace, self.ispace).T
        y.shape = x.shape + (self.mstar,)
        return y

    def get_mesh(self):
        """Get the mesh points on which the solution is specified

        Returns
        -------
        mesh : ndarray of float, shape (nmesh,)
        """
        return self.fspace[0:self.nmesh]

    mesh = property(fget=get_mesh)
    """The mesh on which the solution is specified"""

    def get_mesh_values(self):
        """Get the solution at the mesh points

        Returns
        -------
        values : ndarray
            ``self(self.mesh)``
        """
        return self(self.mesh)


## Problem types

REGULAR = 0
"""The problem is regular"""
SENSITIVE = 1
"""The problem is sensitive. The nonlinear iteration should not rely on \
past covergence."""

## Verbosity

SILENT = 0
"""Print no messages"""
INFO = 1
"""Print selected output"""
DEBUG = 2
"""Print debug output"""

## COLNEW

def solve(boundary_points,
          degrees, fsub, gsub,
          dfsub=None, dgsub=None,
          left=None, right=None,
          is_linear=False,
          initial_guess=None,
          coarsen_initial_guess_mesh=True,
          initial_mesh=None,
          tolerances=None,
          adaptive_mesh_selection=True,
          verbosity=0,
          collocation_points=None,
          extra_fixed_points=None,
          problem_regularity=REGULAR,
          maximum_mesh_size=100,
          vectorized=True,
          is_complex=False,
          ):
    r"""
    Solve a multi-point boundary value problem for a system of ODEs.

    The mixed-order system is::

        ncomp = len(degrees)
        mstar = sum(degrees)

        1 <= min(degrees) <= max(degrees) <= 4

        u_i^{(m_i)}(x) = f_i(x, z(x))       i = 0, ..., ncomp-1
                                            left <= x <= right

        g_j(zeta_j, z(zeta_j)) = 0          j = 0, ..., mstar-1

    where ``u(x)`` is the solution vector at position ``x`` and
    ``zeta = boundary_points`` specifies the boundary points.

    The solution vector is represented by ``z``-vector::

        z = [u_1, u_1', ..., u_1^{m_1-1}, u_2, u_2', ..., u_{mstar-1}]

    It is of shape (mstar,) and contains derivatives of orders < m_i.

    .. note::

        Colnew has the hard-coded problem size limits::
            ncomp <= 256
            mstar <= 512

    Parameters
    ----------
    boundary_points
        Points where i:th boundary condition is given, as a (mstar,) array,
        with left <= boundary_points[i] <= right for all i.
        It must be sorted in increasing order.
    degrees : list of integers
        Degree of i:th equation is ``degree[i]``.
        It is required that ``1 <= degree[i] <= 4``.
    fsub : callable
        Function ``f``, given as ``def fsub(x, z): return f``, where::

            x[j]    = x_j                             (nx,)
            z[i, k] = z_i(x[k])                       (mstar, nx)
            f[i, k] = f_i(x[k], z[:,k])               (ncomp, nx)

        If not vectorized, the last dimension is omitted for all variables.
        The function must be local: f[:,k] can only depend on z[:,k].
    gsub : callable
        Function ``g``, given as ``def gsub(z): return g``, where::

            z[i, j] = z_i(u(zeta_j))                  (mstar, mstar)
            g[i]    = g_i(zeta_i, z(u(zeta_i)))       (mstar,)

        Boundary conditions must be separated: g[:, j] may depend only
        on z[:, j].
    dfsub : callable, optional
        Jacobian of ``f``, given as ``def dfsub(x, z): return df``, where::

            x[j]        = x_j                         (nx,)
            z[j, k]     = z_j(x_k)                    (mstar, nx)
            df[i, j, k] = d f[i,k] / d z[j,k]         (ncomp, mstar, nx)

        If not vectorized, the last dimension is omitted for all variables.
        If None, a simple difference approximation is used.
    dgsub : callable, optional
        Jacobian of ``g``, given as ``def dgsub(z): return dg``, where::

            z[i, j]  = z_i(u(zeta_j))                 (mstar, mstar)
            dg[i, j] = (d g_i / d z_j)(zeta_i, z)     (mstar, mstar)

        If None, a simple difference approximation is used.
    left : float, optional
        The left boundary point. If None, ``left = min(boundary_points)``.
    right : float, optional
        The right boundary point. If None, ``right = max(boundary_points)``.
    vectorized : bool, optional
        Are the functions `fsub`, `dfsub` and `initial_guess` vectorized?
    is_linear : bool, optional
        Is the system of equations linear?
    initial_guess : callable or Solution, optional
        Initial guess for continuation.
        Can be

        1. Callable ``def guess(x): return z, dm``, where::

              x[j]     = x_j                     (nx,)
              z[i, j]  = z_i(u(x_j))             (mstar, nx)
              dm[i, k] = u_i^{m_i}(x_j)          (ncomp, nx)

           If not vectorized, the last dimension is omitted for all
           variables.
        2. Previously obtained `Solution`
        3. None, indicating that a default initial guess is to be used.

    tolerances : list of float, optional
        Tolerances for components of the solution.
        ``tolerance[i]`` gives the tolerance for i:th component of z-vector.
        If ``tolerance[i] == 0``, then no tolerance is imposed for that
        component.
    adaptive_mesh_selection : bool, optional
        Use adaptive mesh selection. If disabled, trivial mesh refinement
        is used -- in this case the initial mesh to use must be given in
        ``initial_mesh``.
    verbosity : int, optional
        Amount of messages to show. 0 means silent, 1 selected printout,
        and 2 diagnostic printout.
    collocation_points : int, optional
        Number of collocation points in each subinterval, or None for
        a sensible default. It is required that
        ``max(degrees) <= collocation_points <= 7``.
    extra_fixed_points : list of float, optional
        Points to fix in the mesh, in addition to boundary_points.
        (E.g. known boundary layers etc.)
    problem_regularity : int, optional
        How regular the problem is. Can be REGULAR (0) or SENSITIVE (1).
        Usually, SENSITIVE should not be needed.
    maximum_mesh_size : int, optional
        Maximum number of points to allow in the mesh.
    is_complex : bool, optional
        Whether the problem is complex-valued.
        The equation must be analytical in the unknown variables.

    Returns
    -------
    sol : Solution
        Object representing the solution.

    Raises
    ------
    ValueError
        Invalid input
    scikits.bvp1lg.NoConvergence
        Numerical convergence problems
    scikits.bvp1lg.TooManySubintervals
        ``maximum_mesh_size`` too small to satisfy tolerances
    scikits.bvp1lg.SingularCollocationMatrix
        Singular collocation matrix (check your jacobians)
    SystemError
        Invalid output from user routines. (FIXME: these should be fixed)

    """

    try:
        _colnew_enter()
        return _colnew_solve(boundary_points,
                             degrees, fsub, gsub,
                             dfsub, dgsub,
                             left, right,
                             is_linear,
                             initial_guess,
                             coarsen_initial_guess_mesh,
                             initial_mesh,
                             tolerances,
                             adaptive_mesh_selection,
                             verbosity,
                             collocation_points,
                             extra_fixed_points,
                             problem_regularity,
                             maximum_mesh_size,
                             vectorized,
                             is_complex)
    finally:
        _colnew_exit()

def _colnew_solve(boundary_points,
                  degrees, fsub, gsub,
                  dfsub, dgsub,
                  left, right,
                  is_linear,
                  initial_guess,
                  coarsen_initial_guess_mesh,
                  initial_mesh,
                  tolerances,
                  adaptive_mesh_selection,
                  verbosity,
                  collocation_points,
                  extra_fixed_points,
                  problem_regularity,
                  maximum_mesh_size,
                  vectorized,
                  is_complex):

    ## Handle complex equations
    if is_complex:
        c_adapter = _complex_adapter.ComplexAdapter(boundary_points, degrees,
                                                    fsub, gsub, dfsub, dgsub,
                                                    tolerances)

        boundary_points = c_adapter.boundary_points
        degrees = c_adapter.degrees
        fsub = c_adapter.fsub
        gsub = c_adapter.gsub
        dfsub = c_adapter.dfsub
        dgsub = c_adapter.dgsub
        tolerances = c_adapter.tolerances


    ## Check degrees

    ncomp = len(degrees)
    mstar = int(sum(degrees))

    if np.sometrue(list(map(lambda x: x <= 0 or x > 4, degrees))):
        raise ValueError("Invalid value for ``degrees``")

    if ncomp <= 0 or mstar <= 0:
        raise ValueError("Invalid value for ``degrees``: no equations")

    # keep these in sync with colnew.f
    if ncomp > 256:
        raise ValueError("Too many equations")
    if mstar > 512:
        raise ValueError("Too many unknown variables")

    ## Defaults

    if collocation_points == None:
        collocation_points = 0
    elif collocation_points < max(degrees) or collocation_points > 7:
        raise ValueError("Invalid number of collocation points")

    if extra_fixed_points == None:
        extra_fixed_points = []

    if tolerances == None:
        tolerances = np.zeros([mstar])

    if left == None:
        left = min(boundary_points)

    if right == None:
        right = max(boundary_points)

    ## Calculate needed workspace size

    k = int(collocation_points)
    kd = k * ncomp
    kdm = kd + mstar
    nsizei = 3 + kdm
    nispace = maximum_mesh_size * nsizei

    nrec = 0
    nsizef = 4 + 3*mstar + (5+kd) * kdm + (2*mstar-nrec)*2*mstar
    nfspace = maximum_mesh_size * nsizef

    ## Allocate work space

    ispace = np.empty([nispace], np.int32)
    fspace = np.empty([nfspace], np.float64)

    ## Boundary points

    if len(boundary_points) != mstar:
        raise ValueError("Invalid number of boundary points")

    zeta = np.asarray(boundary_points, np.float64)
    zeta.sort()

    if not np.alltrue(zeta == boundary_points):
        raise ValueError("Invalid ordering of boundary points")

    if not np.alltrue((zeta >= left) & (zeta <= right)):
        raise ValueError("Some boundary points outside range [left, right]")

    ## Fixed points in the mesh

    fixpnt = list(boundary_points) + list(extra_fixed_points)
    fixpnt.sort()
    fixpnt = list(filter(lambda x: x > left and x < right, fixpnt))
    fixpnt = np.unique(np.array(fixpnt, np.float_).ravel())

    ## Verbosity

    if verbosity < 0:
        verbosity = 0
    elif verbosity > 2:
        verbosity = 2

    ## Tolerances

    if len(tolerances) != mstar:
        raise ValueError("Invalid number of tolerances")

    tolerances = np.asarray(tolerances, np.float64).ravel()
    ltol = np.where(tolerances > 0)[0]
    tol = tolerances[ltol]
    ltol += 1 # Fortran-style indexing

    ## Parameters to COLNEW

    ipar = np.array([
        1 - int(is_linear),  # is the problem nonlinear?
        collocation_points,  # no. collocation points per subinterval
        10,                  # no. subintervals in initial mesh
        len(ltol),           # no. solution and derivative tolerances
        len(fspace),         # float workspace length
        len(ispace),         # integer workspace length
        1 - verbosity,       # output control
        0,                   # initial mesh type (see below)
        0,                   # initial guess type (see below)
        problem_regularity,  # problem regularity
        len(fixpnt),         # number of additional fixed points
        ], np.int32)

    if len(fixpnt) == 0:
        fixpnt = np.array([0], np.float64)

    ## Initial guess

    def dummy_guess(x): raise ValueError("Invalid initial guess")

    guess_func = dummy_guess

    if isinstance(initial_guess, Solution):
        if initial_mesh == None:
            ispace[:len(initial_guess.ispace)] = initial_guess.ispace
            fspace[:len(initial_guess.fspace)] = initial_guess.fspace

            ipar[2] = ispace[0]

            if coarsen_initial_guess_mesh:
                ipar[8] = 3
            else:
                ipar[8] = 2
        else:
            if coarsen_initial_guess_mesh:
                raise ValueError("Initial mesh and guess both specified: "
                                 "cannot coarsen")
            n = len(initial_mesh)
            ispace[n:(n+len(initial_guess.ispace))] = initial_guess.ispace
            fspace[n:(n+len(initial_guess.fspace))] = initial_guess.fspace
            ipar[8] = 4
            ipar[2] = n-1
    elif callable(initial_guess):
        ipar[8] = 1
        guess_func = initial_guess
    elif initial_guess == None:
        ipar[8] = 0
    else:
        raise ValueError("Unknown initial_guess")

    ## Initial mesh

    try:
        ipar[2] = int(initial_mesh) # number of points only
        ipar[7] = 0
        initial_mesh = None
    except (TypeError, ValueError):
        pass

    if initial_mesh != None:
        fspace[:len(initial_mesh)] = initial_mesh
        ipar[2] = len(initial_mesh) - 1
        if not adaptive_mesh_selection:
            ipar[7] = 2
        else:
            ipar[7] = 1
    else:
        ipar[7] = 0
        if not adaptive_mesh_selection:
            raise ValueError("Cannot disable mesh selection when no "
                             "initial_mesh given")

    ## Compatibility with non-vectorized functions

    def vectorized_guess(x):
        us = []
        dms = []
        for i, xx in enumerate(x):
            u, dm = guess_func(float(xx))
            us.append(u)
            dms.append(dm)
        return np.transpose(np.asarray(us)), np.transpose(np.asarray(dms))

    def vectorized_f(x, u):
        fs = []
        for i, xx in enumerate(x):
            fs.append(fsub(float(xx), u[:,i]))
        return np.transpose(np.asarray(fs))

    def vectorized_df(x, u):
        dfs = []
        for i, xx in enumerate(x):
            dfs.append(dfsub(float(xx), u[:,i]))
        dfs = np.asarray(dfs)
        return np.swapaxes(np.swapaxes(dfs, 0, 2), 0, 1)

    if vectorized:
        vectorized_guess = guess_func
        vectorized_f = fsub
        vectorized_df = dfsub

    ## Numerical evaluation of Jacobians, if needed

    def numerical_dg(z):
        zero = np.zeros([z.shape[0]])
        # Surprisingly easy: numpy's indexing & broadcasting rocks.
        # Extra reshape needed for gsubs returning matrices.
        return _jacobian.jacobian(
            lambda u: np.reshape(gsub(z + u[:,None]), [mstar]),
            zero)

    if dgsub == None:
        dgsub = numerical_dg

    def numerical_df(x, z):
        zero = np.zeros(z.shape[0])
        # Extra reshape needed for fsubs returning matrices.
        df = _jacobian.jacobian(
            lambda u: np.reshape(vectorized_f(x, z + u[:,None]),
                                 [ncomp, x.shape[0]]),
            zero)
        return np.swapaxes(df, 1, 2) # x-axis comes z-axis

    if dfsub == None:
        vectorized_df = numerical_df

    ## Call COLNEW

    iflag = _colnew.colnew(
        degrees,
        left, right,
        zeta, ipar, ltol, tol, fixpnt, ispace, fspace,
        vectorized_f, vectorized_df,
        gsub, dgsub,
        vectorized_guess)

    ## Check return value

    if iflag == 1:
        pass # ok
    elif iflag == 0:
        raise _error.SingularCollocationMatrix("Singular collocation matrix "
                                               "in COLNEW")
    elif iflag == -1:
        raise _error.TooManySubintervals("Out of storage space in COLNEW. "
                                         "Try increasing maximum_mesh_size.")
    elif iflag == -2:
        raise _error.NoConvergence("Nonlinear iteration did not converge "
                                   "in COLNEW")
    elif iflag == -3:
        raise ValueError("Invalid input data for COLNEW")
    else:
        raise RuntimeError("Unknown error in COLNEW")

    ## Form the result

    solution = Solution(ispace, fspace)

    ## Return
    if is_complex:
        return _complex_adapter.ComplexSolution(solution)
    else:
        return solution


_colnew_stack = []
_colnew_depth = 0
_colnew_commons = [_colnew.colapr, _colnew.colbas, _colnew.colest,
                   _colnew.colloc, _colnew.colmsh, _colnew.colnln,
                   _colnew.colord, _colnew.colout, _colnew.colsid]

def _colnew_enter():
    """
    Push old COLNEW data to stack.

    Colnew itself is written in Fortran using COMMON blocks,
    and so it is not reentrant. We make it reentrant by manually
    pushing and popping the COMMON contents on and off a stack.

    """
    global _colnew_stack, _colnew_depth, _colnew_commons

    _colnew_depth += 1
    if _colnew_depth == 1:
        return # nothing needs to be done yet

    stack_entry = []
    for j, com in enumerate(_colnew_commons):
        stack_sub = {}
        for name in com.__dict__.keys():
            stack_sub[name] = np.array(getattr(com, name), copy=True)
        stack_entry.append(stack_sub)
    _colnew_stack.append(stack_entry)

def _colnew_exit():
    """
    Pop old COLNEW data from stack.
    """
    global _colnew_stack, _colnew_depth, _colnew_commons

    _colnew_depth -= 1
    if _colnew_depth == 0:
        return # nothing needs to be done

    entry = _colnew_stack.pop()
    for com, sub in zip(_colnew_commons, entry):
        for name in com.__dict__.keys():
            getattr(com, name)[...] = sub[name]

def check_jacobians(boundary_points, degrees, fsub, gsub, dfsub, dgsub,
                    vectorized=True, **kw):
    """
    Check that the Jacobian functions match numerically evaluated derivatives.

    Parameters
    ----------
    degrees, boundary_points, fsub, dfsub, gsub, dsub, vectorized
        As for `solve`.
    kw
        Passed on to `jacobian.check_jacobian`

    Raises
    ------
    ValueError
        If the jacobians seem to be invalid.
    """

    xmin = min(boundary_points)
    xmax = max(boundary_points)

    mstar = sum(degrees)
    ncomp = len(degrees)

    ok = True

    # 1. Jacobian of the rhs function

    for k in range(5):
        if not vectorized:
            x = xmin + (xmax - xmin) * np.random.rand()
            _fsub =  lambda u: np.squeeze(fsub(x, u))
            _dfsub = lambda u: np.squeeze(dfsub(x, u))
        else:
            x = xmin + (xmax - xmin) * np.random.rand(1)
            _fsub  = lambda u: np.squeeze(np.asarray(
                np.reshape(fsub(x, np.reshape(u, [mstar, 1])),
                           [ncomp])))
            _dfsub = lambda u: np.squeeze(np.asarray(
                np.reshape(dfsub(x, np.reshape(u, [mstar, 1])),
                           [ncomp, mstar])))

        if not _jacobian.check_jacobian(mstar, _fsub, _dfsub, **kw):
            raise ValueError("dfsub may be invalid")

    # 2. Jacobians for the boundary conditions
    #
    # This is a bit subtle: we need to also check that each function
    # g_i depends only on u(zeta_i). But we need to note that
    # u(zeta_i) may appear multiple times in the vector passed to gsub
    # and dgsub.
    #

    indep = list(np.unique(boundary_points))
    indep_map = [indep.index(p) for p in boundary_points]

    def _get_u(z):
        z = np.reshape(z, [mstar, len(indep)])
        u = np.empty([mstar, mstar])
        for i, j in enumerate(indep_map):
            u[:,i] = z[:,j]
        return u

    def _gsub(z):
        g = gsub(_get_u(z))
        return g

    def _dgsub(z):
        dg = dgsub(_get_u(z))
        d = np.zeros([mstar, mstar, len(indep)])
        for i, j in enumerate(indep_map):
            d[i,:,j] = dg[i, :]
        d.shape = (mstar, mstar*len(indep))
        return d

    if not _jacobian.check_jacobian(mstar*len(indep), _gsub, _dgsub, **kw):
        raise ValueError("dgsub may be invalid")
