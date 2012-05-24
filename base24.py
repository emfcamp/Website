#!/usr/bin/env python

#
# The idea behind these is that they are unambigous when reading and writing
#
# e.g. no ilIL / Oo0 etc.
#
safechars = "2346789BCDFGHJKMPQRTVWXY"

def tob24(val):
  """Convert an int to base24 using a safe charset"""
  assert type(val) == type(42), "must be an int"
  out = ""
  rem = val % 24
  out = safechars[rem] + out
  val = (val - rem) / 24
  while (val > 0):
    rem = val % 24
    out = safechars[rem] + out
    val = (val - rem) / 24
  return out
  
def fromb24(val):
  """Convert a base24 encoded int (as a string) back to an int """
  assert type(val) == type("string"), "must be an string"  
  pos = len(val) - 1
  out = 0
  for l in val:
    idx = safechars.find(l)
    assert idx > -1, "not a valid base24 string"
    out += (24 ** pos) * idx
    pos -= 1
  return out
  
if __name__ == "__main__":

  for n in (0, 1, 2, 10, 11, 23, 24, 25, (24*2) -1, 24*2, (24*2)+1, 99, 100, (24 * 24) - 1, 24 * 24, (24 * 24 * 24)):
    assert n == fromb24(tob24(n)), "didn't work for %d" % (n)
    print n, tob24(n)

  for n in range(23, 49):
    assert n == fromb24(tob24(n)), "didn't work for %d" % (n)

  for n in range((24 * 24) - 1, (24 * 24 * 24)):
    assert n == fromb24(tob24(n)), "didn't work for %d" % (n)

  assert fromb24("2222222223") == 1, "leading 0's don't work"
  assert fromb24("2222222224") == 2, "leading 0's don't work"
  assert fromb24("2222222232") == 24, "leading 0's don't work"

