import itertools
import collections

from geometry import DEFAULT_GEOMETRY, Point, Rect


class Tile:
    REQUIRED_ADJACENT = 3  # Number of adjacent empty tiles that must be present for a move to be legal.

    def __init__(self, *xy, geometry=DEFAULT_GEOMETRY, parent=None):
        self.geometry = geometry
        self.xy = Point(*xy)
        self.origin = (geometry.full_size * self.xy) + geometry.origin
        if self.xy.y % 2:
            self.origin += geometry.altoffset

        self.rect = Rect(self.origin, self.origin + geometry.size)
        self.sample_rect = self.rect + geometry.sample_insets
        self.neighbors = []
        self._element = None
        self.parent = parent
        self._legal = None

    @property
    def x(self):
        return self.xy.x

    @property
    def y(self):
        return self.xy.y

    @property
    def element(self):
        return self._element

    @element.setter
    def element(self, value):
        if value == self._element:
            return
        previous = self._element
        self._element = value
        if self.parent:
            self.parent.element_changed(self, previous, value)

    @property
    def legal(self):
        return self.predict_legality()

    def real_neighbors(self):
        yield from (n for n in self.neighbors if n is not None)

    def nonempty_neighbors(self):
        yield from (n for n in self.neighbors if n is not None and n.element is not None)

    def expire_legality(self, onlyif=None):
        """Forgets current legality status, causing it to be updated on next request."""
        if onlyif is not None and self._legal is not onlyif:
            return
        self._legal = None

    def predict_legality(self, removed=None):
        """
        Calculates legality status, assuming tiles in `removed` are removed.

        If self._legal is already True, returns True immediately (since removing additional tiles will have no effect)

        If `ignore` is None or has no impact on legality, the current cached legality status will be updated.
        Reasons legality may not be affected include:
            - The tile is illegal anyways.
            - None of the tiles in 'ignore' are adjacent, or they all are already empty.
            - Adjacency criteria are met even without the tiles in `ignore` being considered.

        :param removed: Set of tiles to ignore.  None = ignore no tiles.
        :return: True if this tile is legal, False otherwise.
        """
        if self._legal or (not removed and self._legal is False):
            return self._legal
        if removed is None:
            removed = set()

        def _gen():
            cache = []
            cache_count = self.REQUIRED_ADJACENT - 1
            for neighbor in self.neighbors:
                if neighbor is None or neighbor.element is None:
                    result = (True, True)   # Actual, predicted
                elif neighbor in removed:
                    result = (False, True)  # Actual, predicted
                else:
                    result = (False, False)  # Actual, predicted
                    cache_count = 0  # Stop cacheing (the 'False' results don't need to be repeated)
                if cache_count:
                    cache.append(result)
                    cache_count -= 1
                yield result
            yield from cache

        result = False     # What we'll return at the end if we don't bail early.
        actual_run = 0         # Actual run of legal tiles
        predicted_run = 0      # Predicted run of legal tiles, counting `removed`

        for actual, predicted in _gen():
            if actual:
                actual_run += 1
                if actual_run >= self.REQUIRED_ADJACENT:
                    self._legal = True
                    return True
            else:
                actual_run = 0

            if predicted:
                predicted_run += 1
                if predicted_run >= self.REQUIRED_ADJACENT:
                    result = True
            else:
                predicted_run = 0

        # If we reach here, it's not ACTUALLY legal so update status accordingly.
        self._legal = False
        # But it might be predicted legal...
        return result

    def affected_neighbors(self):
        """Returns a list of neighbors that would become legal if this tile is removed."""
        ignore = {self}
        result = []
        for neighbor in self.nonempty_neighbors():
            if neighbor.predict_legality(removed=ignore):
                if neighbor.legal:
                    continue
                result.append(neighbor)
        return result

    @classmethod
    def all_neighbors(cls, tiles):
        """
        Returns the set of all neighbors of `tiles`.
        :param tiles: Tiles to check
        :return: All neighbors, excluding tiles in `tiles`
        """
        neighbors = set()
        for tile in tiles:
            if tile is None:
                continue
            neighbors.update(tile.real_neighbors())

        neighbors.discard(None)
        neighbors.difference_update(tiles)
        return neighbors

    @classmethod
    def affected_tiles(cls, tiles):
        """Returns a set of tiles that will become legal if all tiles in `tiles` are removed."""
        affected = set()
        for tile in cls.all_neighbors(tile for tile in tiles if tile is not None and tile.element is not None):
            if tile.element is None:
                continue
            if tile.predict_legality(tiles) and not tile.legal:  # Order matters!
                affected.add(tile)
        return affected

    def __repr__(self):
        status = self.element or 'empty'
        if self._legal:
            status  += ', legal'
        elif self._legal is None:
            status += ', ???'
        return f"{self.__class__.__name__}({self.x}, {self.y})  {status}"


class CatalogDictionary(collections.defaultdict):
    def __missing__(self, key):
        return tuple()


class Tileset:
    CARDINALS = {'water', 'earth', 'fire', 'air'}
    METALS = ('mercury', 'tin', 'iron', 'copper', 'silver', 'gold')

    def __init__(self, geometry=DEFAULT_GEOMETRY):
        diameter = 2*geometry.radius - 1

        self.rows = []
        self.tiles = []

        self.catalog = CatalogDictionary()

        # Pad with a row of empties for easier neighbor calculations later.
        blank_row = list(itertools.repeat(None, diameter + 2))
        self.rows.append(blank_row)

        # Used for mapping screenspace coordinates to boardspace
        hoffset = (geometry.radius - 1) // 2

        for y in range(0, diameter):
            row = list(blank_row)
            self.rows.append(row)
            count = diameter - abs(geometry.radius - (y+1))
            start = (diameter - count) // 2
            for x in range(start, start+count):
                t = Tile(x-hoffset, y, parent=self)
                self.tiles.append(t)
                row[x+1] = t

        # End padding, too.
        self.rows.append(blank_row)

        # Calculate adjacency data
        for y, row in enumerate(self.rows):
            altrow = -((y+1)%2)
            if y == 0 or y > diameter:
                continue
            above = self.rows[y-1]
            below = self.rows[y+1]
            for x, tile in enumerate(row):
                if tile is None:
                    continue

                # Starting from the left and going clockwise
                tile.neighbors = [
                    row[x-1],  # Left
                    above[x+altrow],  # Upper left
                    above[x+altrow+1],  # Upper right
                    row[x+1],  # Right
                    below[x+altrow+1],  # Lower right
                    below[x+altrow],  # Lower left
                ]

    def element_changed(self, tile, previous, current):
        """Called when a child tile's element is changed.  Used to update the catalog and legality data."""
        if previous == current:
            return  # Nothing changed.
        if previous is not None:
            self.catalog[previous].discard(tile)
        if current is not None:
            self.catalog.setdefault(current, set()).add(tile)

        if (previous is None) is (current is None):
            return  # No element change, thus no legality changes.
        for neighbor in tile.real_neighbors():
            # If we're gaining an element, expire anything that was previously legal.
            # If we're losing an element, expire anything that was previously not legal.
            neighbor.expire_legality(previous is None)

    def legal_tiles(self):
        """Yields a sequence of tiles that are legal."""
        return set(t for t in self.tiles if t.legal and t.element is not None)

    def cardinal_counts(self):
        return {e: self.count(e) for e in self.CARDINALS}

    def remaining_metals(self):
        return list(list(self.catalog[e])[0] for e in self.METALS if self.catalog[e])

    def count(self, element):
        return len(self.catalog[element])

    def bitmap(self):
        """
        Returns an integer representing which tiles are empty.
        """
        result = 0
        for tile in self.tiles:
            result <<= 1
            if tile.element:
                result |= 1

        return result
