# coding: utf-8
import os
import sys
import string
from shlex import shlex
from io import open
from typing import Any, Callable, Dict, TypeVar, overload

from configparser import ConfigParser, NoOptionError
text_type = str


DEFAULT_ENCODING = 'UTF-8'
T = TypeVar('T')
R = TypeVar('R')

# Python 3.10 don't have strtobool anymore. So we move it here.
TRUE_VALUES = {"y", "yes", "t", "true", "on", "1"}
FALSE_VALUES = {"n", "no", "f", "false", "off", "0"}

def strtobool(value):
    if isinstance(value, bool):
        return value
    value = value.lower()

    if value in TRUE_VALUES:
        return True
    elif value in FALSE_VALUES:
        return False

    raise ValueError("Invalid truth value: " + value)


class UndefinedValueError(Exception):
    pass


class Repository(object):
    def __init__(self, source='', encoding=DEFAULT_ENCODING):
        pass

    def __contains__(self, key: str) -> bool:
        raise NotImplementedError

    def __getitem__(self, key: str) -> str:
        raise NotImplementedError


class RepositoryEmpty(Repository):
    def __init__(self, source='', encoding=DEFAULT_ENCODING):
        pass

    def __contains__(self, key):
        return False

    def __getitem__(self, key):
        return None


class RepositoryIni(Repository):
    """
    Retrieves option keys from .ini files.
    Supports multiple sections.
    """
    SECTION = 'settings'

    def __init__(self, source: str, encoding=DEFAULT_ENCODING):
        self.parser = ConfigParser()
        with open(source, encoding=encoding) as file_:
            self.parser.read_file(file_)

    def __contains__(self, key: str) -> bool:
        if '.' in key:
            section, value = key.rsplit('.', 1)
            return self.parser.has_option(section, value)
        return self.parser.has_option(self.SECTION, key)

    def __getitem__(self, key: str) -> str:
        try:
            if '.' in key:
                section, value = key.rsplit('.', 1)
                return self.parser.get(section, value)
            else:
                return self.parser.get(self.SECTION, key)
        except NoOptionError:
            raise KeyError(key)


class RepositoryEnv(Repository):
    """
    Retrieves option keys from .env files with fall back to os.environ.
    """
    def __init__(self, source: str, encoding=DEFAULT_ENCODING):
        self.data: Dict[str, str] = {}

        with open(source, encoding=encoding) as file_:
            for line in file_:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip()
                if len(v) >= 2 and ((v[0] == "'" and v[-1] == "'") or (v[0] == '"' and v[-1] == '"')):
                    v = v[1:-1]
                self.data[k] = v

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def __getitem__(self, key) -> str:
        return self.data[key]


class RepositorySecret(RepositoryEmpty):
    """
    Retrieves option keys from files,
    where title of file is a key, content of file is a value
    e.g. Docker swarm secrets
    """

    def __init__(self, source='/run/secrets/'):
        self.data: Dict[str, str] = {}

        ls = os.listdir(source)
        for file in ls:
            with open(os.path.join(source, file), 'r') as f:
                self.data[file] = f.read()

    def __contains__(self, key) -> bool:
        return key in self.data

    def __getitem__(self, key) -> str:
        return self.data[key]


class Undefined(object):
    """
    Class to represent undefined type.
    """


# Reference instance to represent undefined values
undefined = Undefined()

def _cast_do_nothing(value: str) -> str:
    return value



class Config(object):
    """
    Handle .env file format used by Foreman.
    """

    def __init__(self, repository: Repository):
        self.repository = repository

    def _cast_boolean(self, value: str) -> bool:
        """
        Helper to convert config values to boolean as ConfigParser do.
        """
        value = str(value)
        return bool(value) if value == '' else bool(strtobool(value))

    @overload
    def get(
        self,
        option,
        *,
        default: str | Undefined = undefined,
        cast: Callable[[str], str] = _cast_do_nothing,
    ) -> str:
        ...

    @overload
    def get(
        self,
        option,
        *,
        default: T | Undefined = undefined,
        cast: Callable[[str], T],
    ) -> T:
        ...

    def get(
        self,
        option,
        *,
        default: Any | Undefined = undefined,
        cast: Callable[[str], Any] = _cast_do_nothing,
    ) -> Any:
        """
        Return the value for option or default if defined.
        """

        if cast is bool:
            cast = self._cast_boolean

        # We can't avoid __contains__ because value may be empty.
        if option in os.environ:
            value = cast(os.environ[option])
        elif option in self.repository:
            value = cast(self.repository[option])
        else:
            if isinstance(default, Undefined):
                raise UndefinedValueError('{} not found. Declare it as envvar or define a default value.'.format(option))
            value = default

        return value

    @overload
    def __call__(
        self,
        option,
        *,
        default: str | Undefined = undefined,
        cast: Callable[[str], str] = _cast_do_nothing,
    ) -> str:
        ...

    @overload
    def __call__(
        self,
        option,
        *,
        default: T | Undefined = undefined,
        cast: Callable[[str], T],
    ) -> T:
        ...

    def __call__(
        self,
        option,
        *,
        default: Any | Undefined = undefined,
        cast: Callable[[str], Any] = _cast_do_nothing,
    ) -> Any:
        """
        Convenient shortcut to get.
        """
        return self.get(option, default=default, cast=cast)


class SuperConfig(object):
    """
    Autodetects multi config files. If the config file matches the
    extension and is in the search path, it will be loaded.
    Else if the filename matches the direct list, it will be loaded.

    Parameters
    ----------
    search_paths : strs, optional
        Initial search paths. Automatically includes caller's path.
    """
    EXTS = {'.env': RepositoryEnv, '.ini': RepositoryIni}
    DIRECT = ['.env', 'settings.ini']

    def __init__(self, *search_paths: str):
        self.search_paths = search_paths
        self.configs = []
        self.config_paths = set()

    def _load_in_dir(self, path: str):
        # if the path is in search_paths and extension matches, load it.
        # else if the filename matches direct, load it.
        for filename in os.listdir(path):
            name, ext = os.path.splitext(os.path.basename(filename))
            ext = name if name.startswith('.') else ext
            if (
                (path in self.search_paths and ext in self.EXTS)
                or filename in self.DIRECT
            ):
                full_path = os.path.join(path, filename)
                if full_path not in self.config_paths:
                    self.config_paths.add(full_path)
                    self.configs.append(Config(self.EXTS[ext](os.path.join(path, filename))))


    def _find_files(self, path: str):
        self._load_in_dir(path)
        parent = os.path.dirname(path)
        if (
            parent
            and os.path.normcase(parent) != os.path.normcase(os.path.abspath(os.sep))
            and path != os.getcwd()
        ):
            self._find_files(parent)

    def _caller_path(self):
        # MAGIC! Get the caller's module path.
        frame = sys._getframe()
        path = os.path.dirname(frame.f_back.f_back.f_code.co_filename) # type: ignore
        return path

    @overload
    def __call__(
        self,
        option,
        *,
        default: str | Undefined = undefined,
        cast: Callable[[str], str] = _cast_do_nothing,
    ) -> str:
        ...

    @overload
    def __call__(
        self,
        option,
        *,
        default: T | Undefined = undefined,
        cast: Callable[[str], T],
    ) -> T:
        ...

    def __call__(
        self,
        option,
        *,
        default: Any | Undefined = undefined,
        cast: Callable[[str], Any] = _cast_do_nothing,
    ) -> Any:
        if not len(self.configs):
            for path in [self._caller_path(), *self.search_paths]:
                self._find_files(path)

        for idx, config in enumerate(self.configs):
            try:
                # default only on last one
                if idx == len(self.configs) - 1:
                    return config(option, default=default, cast=cast)
                return config(option, cast=cast)
            except UndefinedValueError:
                pass
        raise UndefinedValueError('{} not found. Declare it as envvar or define a default value.'.format(option))


# A pré-instantiated AutoConfig to improve decouple's usability
# now just import config and start using with no configuration.
config = SuperConfig()

# Helpers

class Csv(object):
    """
    Produces a csv parser that return a list of transformed elements.
    """

    def __init__(self, cast=text_type, delimiter=',', strip=string.whitespace, post_process=list):
        """
        Parameters:
        cast -- callable that transforms the item just before it's added to the list.
        delimiter -- string of delimiters chars passed to shlex.
        strip -- string of non-relevant characters to be passed to str.strip after the split.
        post_process -- callable to post process all casted values. Default is `list`.
        """
        self.cast = cast
        self.delimiter = delimiter
        self.strip = strip
        self.post_process = post_process

    def __call__(self, value):
        """The actual transformation"""
        if value is None:
            return self.post_process()

        transform = lambda s: self.cast(s.strip(self.strip))

        splitter = shlex(value, posix=True)
        splitter.whitespace = self.delimiter
        splitter.whitespace_split = True

        return self.post_process(transform(s) for s in splitter)


class Choices(object):
    """
    Allows for cast and validation based on a list of choices.
    """

    def __init__(self, flat=None, cast=text_type, choices=None):
        """
        Parameters:
        flat -- a flat list of valid choices.
        cast -- callable that transforms value before validation.
        choices -- tuple of Django-like choices.
        """
        self.flat = flat or []
        self.cast = cast
        self.choices = choices or []

        self._valid_values = []
        self._valid_values.extend(self.flat)
        self._valid_values.extend([value for value, _ in self.choices])

    def __call__(self, value):
        transform = self.cast(value)
        if transform not in self._valid_values:
            raise ValueError((
                    'Value not in list: {!r}; valid values are {!r}'
                ).format(value, self._valid_values))
        else:
            return transform
