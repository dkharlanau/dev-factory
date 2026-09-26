"""Independent, predeclared behavioral probes; run only after a variant finishes."""
import itertools
import random
import sys
import tracemalloc
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
import more_itertools as mi


def small():
    class Falsy(ValueError):
        def __bool__(self): return False
    class BadRepr:
        def __repr__(self): raise RuntimeError('repr should not run')
    for fn, values, key in [(mi.one, [], 'too_short'), (mi.one, [BadRepr(),BadRepr()], 'too_long'), (mi.only, [BadRepr(),BadRepr()], 'too_long')]:
        exc=Falsy('expected')
        try: fn(values, **{key:exc})
        except BaseException as actual: assert actual is exc, (fn,key,type(actual))
        else: raise AssertionError('exception absent')


def medium():
    for args in [(-1,), (0,), (1,), (2,), (10000,), (100,200), (1000,2000,10), (2000,1000,-10)]:
        assert sorted(mi.random_ordered_range(*args))==sorted(range(*args)), args
    try: list(mi.random_ordered_range(0,5,0))
    except ValueError: pass
    else: raise AssertionError('zero step accepted')
    random.seed(409)
    distinct_orders=len({tuple(mi.random_ordered_range(6)) for _ in range(3000)})
    print('distinct_orders',distinct_orders)
    assert distinct_orders>1
    tracemalloc.start()
    it=mi.random_ordered_range(10**6)
    head=list(itertools.islice(it,1000))
    peak=tracemalloc.get_traced_memory()[1];tracemalloc.stop()
    assert len(set(head))==1000 and all(0<=x<10**6 for x in head)
    assert peak<4_000_000, peak
    assert 'random_ordered_range' in mi.__all__ if hasattr(mi,'__all__') else hasattr(mi,'random_ordered_range')
    for path in ['more_itertools/more.pyi','README.rst','docs/api.rst']:
        assert 'random_ordered_range' in open(path).read(), path


def debug():
    for args in [(0.,1.,.1),(1.,0.,-.1),(.1,.5,.1),(Decimal('0.1'),Decimal('0.9'),Decimal('0.1')),(Fraction(1,10),Fraction(1),Fraction(1,10)),(datetime.min,datetime.min+timedelta(days=2),timedelta(days=1)),(datetime.max,datetime.max-timedelta(days=2),-timedelta(days=1))]:
        r=mi.numeric_range(*args)
        assert list(reversed(r))==list(r)[::-1],args
    r=mi.numeric_range(0,10**12)
    assert next(reversed(r))==10**12-1


def refactor():
    for n in range(7):
        for r in range(n+1):
            vals=list(itertools.permutations(range(n),r))
            for i,p in enumerate(vals):
                assert mi.nth_permutation(range(n),r,i)==p
                assert mi.nth_permutation(range(n),r,i-len(vals))==p
    assert mi.nth_permutation(range(10000),2,-1)==(9999,9998)
    for args in [(range(2),3,0),(range(2),1,2),(range(2),1,-3)]:
        try: mi.nth_permutation(*args)
        except (ValueError,IndexError): pass
        else: raise AssertionError(args)
    import inspect
    assert 'factorial(' not in inspect.getsource(mi.nth_permutation)


def long():
    it=mi.seekable(range(100),maxlen=0)
    for n in range(100):
        assert it.peek()==it.peek()==n and bool(it)
        assert next(it)==n and not list(it.elements())
    assert not it and it.peek(default='end')=='end'
    for limit in [None,1,3]:
        it=mi.seekable(range(10),maxlen=limit)
        assert next(it)==0 and next(it)==1
        it.seek(0)
        assert next(it)==(1 if limit==1 else 0)
    tracemalloc.start()
    it=mi.seekable(range(200000),maxlen=0)
    for n in range(200000):
        assert it.peek()==n and next(it)==n
    peak=tracemalloc.get_traced_memory()[1];tracemalloc.stop()
    assert peak<2_000_000,peak
    it=mi.seekable(range(10),maxlen=0)
    assert it.peek()==0
    it.relative_seek(2)
    assert next(it)==2

if __name__=='__main__':
    globals()[sys.argv[1]]()
    print('ORACLE PASS',sys.argv[1])
