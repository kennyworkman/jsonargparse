"""Metods to add arguments based on class/method/function signatures."""

import inspect
from enum import Enum
from typing import Optional, Container, Type, Callable

from .util import _issubclass
from .actions import ActionEnum, _ActionConfigLoad, _ActionHelpClassPath
from .typing import is_optional
from .jsonschema import ActionJsonSchema
from .optionals import docstring_parser_support, import_docstring_parse, dataclasses_support, import_dataclasses


__all__ = ['SignatureArguments']


class SignatureArguments:
    """Methods to add arguments based on signatures to an ArgumentParser instance."""

    def add_class_arguments(
        self,
        theclass: Type,
        nested_key: Optional[str] = None,
        as_group: bool = True,
        as_positional: bool = False,
        skip: Optional[Container[str]] = None,
    ) -> int:
        """Adds arguments from a class based on its type hints and docstrings.

        Note: Keyword arguments without at least one valid type are ignored.

        Args:
            theclass: Class from which to add arguments.
            nested_key: Key for nested namespace.
            as_group: Whether arguments should be added to a new argument group.
            as_positional: Whether to add required parameters as positional arguments.
            skip: Names of parameters that should be skipped.

        Returns:
            Number of arguments added.

        Raises:
            ValueError: When not given a class.
            ValueError: When there are required parameters without at least one valid type.
        """
        if not inspect.isclass(theclass):
            raise ValueError('Expected "theclass" argument to be a class object.')

        def docs_func(base):
            return [base.__init__.__doc__, base.__doc__]

        def sign_func(base):
            return base.__init__

        return self._add_signature_arguments(inspect.getmro(theclass),
                                             nested_key,
                                             as_group,
                                             as_positional,
                                             skip,
                                             docs_func,
                                             sign_func,
                                             skip_first=True)


    def add_method_arguments(
        self,
        theclass: Type,
        themethod: str,
        nested_key: Optional[str] = None,
        as_group: bool = True,
        as_positional: bool = False,
        skip: Optional[Container[str]] = None,
    ) -> int:
        """Adds arguments from a class based on its type hints and docstrings.

        Note: Keyword arguments without at least one valid type are ignored.

        Args:
            theclass: Class which includes the method.
            themethod: Name of the method for which to add arguments.
            nested_key: Key for nested namespace.
            as_group: Whether arguments should be added to a new argument group.
            as_positional: Whether to add required parameters as positional arguments.
            skip: Names of parameters that should be skipped.

        Returns:
            Number of arguments added.

        Raises:
            ValueError: When not given a class or the name of a method of the class.
            ValueError: When there are required parameters without at least one valid type.
        """
        if not inspect.isclass(theclass):
            raise ValueError('Expected "theclass" argument to be a class object.')
        if not hasattr(theclass, themethod) or not callable(getattr(theclass, themethod)):
            raise ValueError('Expected "themethod" argument to be a callable member of the class.')

        skip_first = not isinstance(inspect.getattr_static(theclass, themethod), staticmethod)
        themethod = getattr(theclass, themethod)

        return self._add_signature_arguments([themethod],
                                             nested_key,
                                             as_group,
                                             as_positional,
                                             skip,
                                             skip_first=skip_first)


    def add_function_arguments(
        self,
        function: Callable,
        nested_key: Optional[str] = None,
        as_group: bool = True,
        as_positional: bool = False,
        skip: Optional[Container[str]] = None,
    ) -> int:
        """Adds arguments from a function based on its type hints and docstrings.

        Note: Keyword arguments without at least one valid type are ignored.

        Args:
            function: Function from which to add arguments.
            nested_key: Key for nested namespace.
            as_group: Whether arguments should be added to a new argument group.
            as_positional: Whether to add required parameters as positional arguments.
            skip: Names of parameters that should be skipped.

        Returns:
            Number of arguments added.

        Raises:
            ValueError: When not given a callable.
            ValueError: When there are required parameters without at least one valid type.
        """
        if not callable(function):
            raise ValueError('Expected "function" argument to be a callable object.')

        return self._add_signature_arguments([function],
                                             nested_key,
                                             as_group,
                                             as_positional,
                                             skip)


    def _add_signature_arguments(
        self,
        objects,
        nested_key: Optional[str],
        as_group: bool,
        as_positional: bool,
        skip: Optional[Container[str]],
        docs_func: Callable = lambda x: [x.__doc__],
        sign_func: Callable = lambda x: x,
        skip_first: bool = False,
    ) -> int:
        """Adds arguments from parameters of objects based on signatures and docstrings.

        Args:
            objects: Objects from which to add signatures.
            nested_key: Key for nested namespace.
            as_group: Whether arguments should be added to a new argument group.
            as_positional: Whether to add required parameters as positional arguments.
            skip: Names of parameters that should be skipped.
            docs_func: Function that returns docstrings for a given object.
            sign_func: Function that returns signature method for a given object.
            skip_first: Whether to skip first argument, i.e., skip self of class methods.

        Returns:
            Number of arguments added.

        Raises:
            ValueError: When there are required parameters without at least one valid type.
        """
        kinds = inspect._ParameterKind

        def update_has_args_kwargs(base, has_args=True, has_kwargs=True):
            params = list(inspect.signature(sign_func(base)).parameters.values())
            has_args &= any(p._kind == kinds.VAR_POSITIONAL for p in params)
            has_kwargs &= any(p._kind == kinds.VAR_KEYWORD for p in params)
            return has_args, has_kwargs

        ## Determine propagation of arguments ##
        add_types = [(True, True)]
        has_args, has_kwargs = update_has_args_kwargs(objects[0])
        for num in range(1, len(objects)):
            if not (has_args or has_kwargs):
                objects = objects[:num]
                break
            add_types.append((has_args, has_kwargs))
            has_args, has_kwargs = update_has_args_kwargs(objects[num], has_args, has_kwargs)

        ## Gather docstrings ##
        doc_group, doc_params = self._gather_docstrings(objects, docs_func)

        ## Create group if requested ##
        group = self._create_group_if_requested(objects[0], nested_key, as_group, doc_group)

        ## Add objects arguments ##
        added_args = set()
        if skip is None:
            skip = set()
        if dataclasses_support:
            dataclasses = import_dataclasses('_add_signature_arguments')
        for obj, (add_args, add_kwargs) in zip(objects, add_types):
            for num, param in enumerate(inspect.signature(sign_func(obj)).parameters.values()):
                name = param.name
                kind = param._kind  # type: ignore
                annotation = param.annotation
                default = param.default
                is_required = default == inspect._empty  # type: ignore
                skip_message = 'Skipping parameter "'+name+'" from "'+obj.__name__+'" because of: '
                if kind in {kinds.VAR_POSITIONAL, kinds.VAR_KEYWORD} or \
                   (is_required and skip_first and num == 0) or \
                   (annotation == inspect._empty and not is_required and default is None):  # type: ignore
                    continue
                elif is_required and not add_args:
                    self.logger.debug(skip_message+'Positional parameter but *args not propagated.')  # type: ignore
                    continue
                elif not is_required and not add_kwargs:
                    self.logger.debug(skip_message+'Keyword parameter but **kwargs not propagated.')  # type: ignore
                    continue
                elif name in skip:
                    self.logger.debug(skip_message+'Parameter requested to be skipped.')  # type: ignore
                    continue
                if dataclasses_support and default.__class__ == dataclasses._HAS_DEFAULT_FACTORY_CLASS:
                    default = obj.__dataclass_fields__[name].default_factory()
                if annotation == inspect._empty and not is_required:  # type: ignore
                    annotation = type(default)
                kwargs = {'help': doc_params.get(name)}
                if not is_required:
                    kwargs['default'] = default
                    if default is None and not is_optional(annotation, object):
                        annotation = Optional[annotation]
                elif not as_positional:
                    kwargs['required'] = True
                if annotation in {str, int, float, bool} or \
                   _issubclass(annotation, (str, int, float)):
                    kwargs['type'] = annotation
                elif _issubclass(annotation, Enum):
                    kwargs['action'] = ActionEnum(enum=annotation)
                else:
                    try:
                        kwargs['action'] = ActionJsonSchema(annotation=annotation, enable_path=False)
                    except ValueError as ex:
                        self.logger.debug(skip_message+str(ex))  # type: ignore
                if 'type' in kwargs or 'action' in kwargs:
                    dest = (nested_key+'.' if nested_key else '') + name
                    if dest in added_args:
                        self.logger.debug(skip_message+'Argument already added.')  # type: ignore
                    else:
                        opt_str = dest if is_required and as_positional else '--'+dest
                        group.add_argument(opt_str, **kwargs)
                        added_args.add(dest)
                elif is_required:
                    raise ValueError('Required parameter without a type for '+obj.__name__+' parameter '+name+'.')

        return len(added_args)


    def add_subclass_arguments(
        self,
        baseclass: Type,
        nested_key: str,
        as_group: bool = True,
        metavar: str = '{"class_path":...[,"init_args":...]}',
        help: str = 'Dictionary with "class_path" and "init_args" for any subclass of %(baseclass_name)s.',
        **kwargs
    ):
        """Adds arguments to allow specifying any subclass of the given base class.

        This adds an argument that requires a dictionary with a "class_path"
        entry which must be a import dot notation expression. Optionally any
        init arguments for the class can be given in the "init_args" entry.
        Since subclasses can have different init arguments, the help does not
        show the details of the arguments of the base class. Instead a help
        argument is added that will print the details for a given class path.

        Args:
            baseclass: Base class to use to check subclasses.
            nested_key: Key for nested namespace.
            as_group: Whether arguments should be added to a new argument group.
            metavar: Variable string to show in the argument's help.
            help: Description of argument to show in the help.

        Raises:
            ValueError: When not given a class.
        """
        if not inspect.isclass(baseclass):
            raise ValueError('Expected "baseclass" argument to be a class object.')

        def docs_func(base):
            return [base.__init__.__doc__, base.__doc__]

        doc_group = self._gather_docstrings([baseclass], docs_func)[0]
        group = self._create_group_if_requested(baseclass, nested_key, as_group, doc_group, config_load=False)

        group.add_argument('--'+nested_key+'.help', action=_ActionHelpClassPath(baseclass=baseclass))
        group.add_argument(
            '--' + nested_key,
            type=baseclass,
            enable_path=True,
            metavar=metavar,
            help=(help % {'baseclass_name': baseclass.__name__}),
            **kwargs
        )


    def _gather_docstrings(self, objects, docs_func):
        doc_group = None
        doc_params = {}
        if docstring_parser_support:
            docstring_parse = import_docstring_parse('_gather_docstrings')
            for base in objects:
                for doc in docs_func(base):
                    try:
                        docstring = docstring_parse(doc)
                    except ValueError:
                        self.logger.debug('Failed parsing docstring for '+str(base))
                    else:
                        if docstring.short_description and not doc_group:
                            doc_group = docstring.short_description
                        for param in docstring.params:
                            if param.arg_name not in doc_params:
                                doc_params[param.arg_name] = param.description
        return doc_group, doc_params


    def _create_group_if_requested(self, obj, nested_key, as_group, doc_group, config_load=True):
        group = self
        if as_group:
            if doc_group is None:
                doc_group = str(obj)
            name = obj.__name__ if nested_key is None else nested_key
            group = self.add_argument_group(doc_group, name=name)
            if config_load and nested_key is not None:
                group.add_argument('--'+nested_key, action=_ActionConfigLoad)
        return group
