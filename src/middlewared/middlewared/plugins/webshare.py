import json
import os
import pathlib

import middlewared.sqlalchemy as sa

from middlewared.api import api_method
from middlewared.api.current import (
    WebShareEntry, WebShareUpdateArgs, WebShareUpdateResult,
    WebShareValidateArgs, WebShareValidateResult
)
from middlewared.schema import ValidationErrors
from middlewared.service import CallError, SystemServiceService, private


class WebShareModel(sa.Model):
    __tablename__ = 'services_webshare'

    id = sa.Column(sa.Integer(), primary_key=True)
    srv_truenas_host = sa.Column(sa.String(255), default='localhost')
    srv_log_level = sa.Column(sa.String(20), default='info')
    srv_session_log_retention = sa.Column(sa.Integer(), default=20)
    srv_enable_web_terminal = sa.Column(sa.Boolean(), default=False)
    srv_bulk_download_pool = sa.Column(sa.String(255), nullable=True)
    srv_search_index_pool = sa.Column(sa.String(255), nullable=True)
    srv_altroots = sa.Column(sa.JSON(dict), default={})
    srv_search_enabled = sa.Column(sa.Boolean(), default=False)
    srv_search_directories = sa.Column(sa.JSON(list), default=[])
    srv_search_max_file_size = sa.Column(sa.Integer(), default=104857600)
    srv_search_supported_types = sa.Column(
        sa.JSON(list),
        default=['image', 'audio', 'video', 'document', 'archive', 'text', 'disk_image']
    )
    srv_search_worker_count = sa.Column(sa.Integer(), default=4)
    srv_search_archive_enabled = sa.Column(sa.Boolean(), default=True)
    srv_search_archive_max_depth = sa.Column(sa.Integer(), default=2)
    srv_search_archive_max_size = sa.Column(sa.Integer(), default=524288000)
    srv_search_index_max_size = sa.Column(sa.Integer(), default=10737418240)
    srv_search_index_cleanup_enabled = sa.Column(sa.Boolean(), default=True)
    srv_search_index_cleanup_threshold = sa.Column(sa.Integer(), default=90)  # Stored as percentage
    srv_search_pruning_enabled = sa.Column(sa.Boolean(), default=False)
    srv_search_pruning_schedule = sa.Column(sa.String(20), default='daily')
    srv_search_pruning_start_time = sa.Column(sa.String(10), default='23:00')


class WebShareService(SystemServiceService):

    class Config:
        datastore = 'services.webshare'
        service = 'webshare'
        datastore_prefix = 'srv_'
        cli_namespace = 'service.webshare'
        role_prefix = 'SHARING'
        entry = WebShareEntry

    @api_method(WebShareValidateArgs, WebShareValidateResult, roles=['SHARING_READ'])
    async def validate(self, data):
        """
        Validate WebShare configuration without saving.
        """
        config = await self.config()
        config.update(data)
        await self._validate(config)

    @api_method(
        WebShareUpdateArgs, WebShareUpdateResult,
        audit='Update WebShare configuration', roles=['SHARING_WRITE']
    )
    async def do_update(self, data):
        """
        Update WebShare service configuration.

        `truenas_host` specifies the TrueNAS API endpoint for authentication.

        `bulk_download_pool` and `search_index_pool` must be valid imported pools.
        The service will automatically create datasets under <pool>/.webshare-private/
        for these features.

        `altroots` defines alternative root paths for file access. Keys and values
        must be unique, and paths must be under /mnt/<poolname>/.

        `search_directories` lists directories to index, which must also be under
        /mnt/<poolname>/.
        """
        old = await self.config()
        new = old.copy()
        new.update(data)

        await self._validate(new)

        # Handle dataset creation/updates
        await self._update_datasets(old, new)

        # Save configuration
        await self.middleware.call(
            'datastore.update',
            self._config.datastore,
            new['id'],
            new,
            {'prefix': self._config.datastore_prefix}
        )

        # Generate configuration files
        await self._generate_config_files()

        # Reload service if running
        if await self.middleware.call('service.started', 'webshare'):
            await self.middleware.call('service.reload', 'webshare')

        return await self.config()

    @private
    async def _validate(self, data):
        """Validate WebShare configuration."""
        verrors = ValidationErrors()

        # Validate pool selections
        boot_pool = await self.middleware.call('boot.pool_name')
        pools = await self.middleware.call('pool.query', [['status', '!=', 'OFFLINE']])
        pool_names = [p['name'] for p in pools if p['name'] != boot_pool]

        for field in ['bulk_download_pool', 'search_index_pool']:
            if data.get(field):
                if data[field] not in pool_names:
                    verrors.add(
                        f'webshare_update.{field}',
                        f'Pool "{data[field]}" is not a valid imported pool'
                    )

        # Validate altroots
        if data.get('altroots'):
            # Check unique keys (handled by dict structure)
            # Check unique values
            values = list(data['altroots'].values())
            if len(values) != len(set(values)):
                verrors.add(
                    'webshare_update.altroots',
                    'Duplicate values are not allowed in altroots'
                )

            # Validate paths
            for name, path in data['altroots'].items():
                await self._validate_pool_path(
                    verrors, 'webshare_update.altroots', name, path, pool_names
                )

        # Validate search directories
        if data.get('search_directories'):
            for idx, path in enumerate(data['search_directories']):
                await self._validate_pool_path(
                    verrors, 'webshare_update.search_directories',
                    f'[{idx}]', path, pool_names
                )

        # Validate time format
        if data.get('search_pruning_start_time'):
            try:
                hour, minute = data['search_pruning_start_time'].split(':')
                if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
                    raise ValueError()
            except (ValueError, AttributeError):
                verrors.add(
                    'webshare_update.search_pruning_start_time',
                    'Invalid time format. Use HH:MM (24-hour format)'
                )

        # Validate numeric ranges
        if data.get('search_index_cleanup_threshold') is not None:
            if not 0 <= data['search_index_cleanup_threshold'] <= 100:
                verrors.add(
                    'webshare_update.search_index_cleanup_threshold',
                    'Threshold must be between 0 and 100 (percentage)'
                )

        verrors.check()

    @private
    async def _validate_pool_path(self, verrors, field_base, field_name, path, pool_names):
        """Validate that a path is under /mnt/<poolname>/ and exists."""
        if not path.startswith('/mnt/'):
            verrors.add(
                f'{field_base}.{field_name}',
                f'Path must be under /mnt/<poolname>/, got: {path}'
            )
            return

        # Extract pool name from path
        path_parts = path[5:].split('/', 1)  # Remove '/mnt/' prefix
        if not path_parts or path_parts[0] not in pool_names:
            verrors.add(
                f'{field_base}.{field_name}',
                f'Path must be under a valid pool in /mnt/, got: {path}'
            )
            return

        # Check if path exists
        if not await self.middleware.call('filesystem.is_path_accessible', path):
            verrors.add(
                f'{field_base}.{field_name}',
                f'Path does not exist or is not accessible: {path}'
            )

    @private
    async def _update_datasets(self, old_config, new_config):
        """Create or update WebShare private datasets."""
        # Define mount paths
        mount_paths = {
            'bulk_download': '/var/cache/webshare/bulk_download',
            'search-index': '/var/cache/webshare/index'
        }

        dataset_configs = [
            ('bulk_download_pool', 'bulk_download', {'compression': 'lz4', 'atime': 'off'}),
            ('search_index_pool', 'search-index', {
                'compression': 'lz4', 'atime': 'off', 'recordsize': '16K'
            })
        ]

        # Create mount directories if they don't exist
        for mount_path in mount_paths.values():
            os.makedirs(mount_path, exist_ok=True)

        for pool_field, dataset_suffix, properties in dataset_configs:
            old_pool = old_config.get(pool_field)
            new_pool = new_config.get(pool_field)

            if old_pool != new_pool:
                # Remove old dataset if pool changed
                if old_pool:
                    old_dataset = f'{old_pool}/.webshare-private/{dataset_suffix}'
                    old_dataset_exists = await self.middleware.call(
                        'zfs.dataset.query',
                        [['name', '=', old_dataset]]
                    )
                    if old_dataset_exists:
                        await self.middleware.call(
                            'zfs.dataset.delete', old_dataset, {'recursive': True}
                        )

            # Create or update dataset if pool is set
            if new_pool:
                parent_dataset = f'{new_pool}/.webshare-private'
                dataset = f'{parent_dataset}/{dataset_suffix}'

                # Create parent if needed
                parent_exists = await self.middleware.call(
                    'zfs.dataset.query',
                    [['name', '=', parent_dataset]]
                )
                if not parent_exists:
                    await self.middleware.call(
                        'zfs.dataset.create', {
                            'name': parent_dataset,
                            'properties': {'mountpoint': 'none'}
                        }
                    )

                # Create dataset
                dataset_exists = await self.middleware.call(
                    'zfs.dataset.query',
                    [['name', '=', dataset]]
                )
                if not dataset_exists:
                    # Add mountpoint to properties
                    dataset_properties = properties.copy()
                    dataset_properties['mountpoint'] = mount_paths[dataset_suffix]

                    await self.middleware.call(
                        'zfs.dataset.create', {
                            'name': dataset,
                            'properties': dataset_properties
                        }
                    )
                else:
                    # Update mountpoint if dataset exists
                    await self.middleware.call(
                        'zfs.dataset.update', dataset,
                        {'properties': {'mountpoint': {'value': mount_paths[dataset_suffix]}}}
                    )

    @private
    async def _generate_config_files(self):
        """Generate configuration files for WebShare services."""
        config = await self.config()

        # Use fixed mount points
        bulk_download_tmp = '/var/cache/webshare/bulk_download' if config['bulk_download_pool'] else None
        search_index_path = '/var/cache/webshare/index' if config['search_index_pool'] else None

        # Create config directories
        config_dirs = [
            '/etc/webshare-auth',
            '/etc/truenas-file-manager',
            '/etc/truesearch'
        ]
        for config_dir in config_dirs:
            pathlib.Path(config_dir).mkdir(parents=True, exist_ok=True)

        # Generate truenas-webshare-auth config
        auth_config = {
            'truenashost': config['truenas_host'],
            'webshare_config_path': '/etc/truenas-file-manager/config.json',
            'log_level': config['log_level'],
            'bulk_download_tmp': bulk_download_tmp or '/var/tmp/truenas-file-manager/bulk-downloads',
            'session_log_retention': config['session_log_retention'],
            'enable_web_terminal': config['enable_web_terminal'],
            'truesearch': {
                'enabled': config['search_enabled'],
                'config': '/etc/truesearch/config.json',
                'debug': config['log_level'] == 'debug'
            }
        }

        with open('/etc/webshare-auth/config.json', 'w') as f:
            json.dump(auth_config, f, indent=2)

        # Generate truenas-file-manager config
        fm_config = {
            'altroots': config['altroots'],
            'bulk_download_tmp': bulk_download_tmp or '/var/tmp/truenas-file-manager/bulk-downloads'
        }

        with open('/etc/truenas-file-manager/config.json', 'w') as f:
            json.dump(fm_config, f, indent=2)

        # Generate truesearch config if search is enabled
        if config['search_enabled']:
            # Convert schedule to interval hours
            schedule_hours = {
                'hourly': 1,
                'daily': 24,
                'weekly': 168
            }

            search_config = {
                'directories': config['search_directories'],
                'index_path': search_index_path or './index',
                'log_level': config['log_level'],
                'max_file_size': config['search_max_file_size'],
                'supported_types': config['search_supported_types'],
                'batch_size': 100,
                'worker_count': config['search_worker_count'],
                'archive': {
                    'max_depth': config['search_archive_max_depth'],
                    'max_entries': 1000,
                    'max_archive_size': config['search_archive_max_size'],
                    'index_contents': config['search_archive_enabled'],
                    'extract_text': False,
                    'supported_formats': ['zip', 'tar', 'gz', 'bz2', 'xz', 'rar', '7z']
                },
                'index_settings': {
                    'max_index_size': config['search_index_max_size'],
                    'max_document_count': 1000000,
                    'cleanup_policy': 'lru',
                    'cleanup_threshold': config['search_index_cleanup_threshold'] / 100.0,
                    'enable_auto_cleanup': config['search_index_cleanup_enabled'],
                    'cleanup_cooldown_minutes': 5,
                    'cleanup_target': 0.8
                },
                'pruning': {
                    'enabled': config['search_pruning_enabled'],
                    'schedule': config['search_pruning_schedule'],
                    'interval_hours': schedule_hours.get(config['search_pruning_schedule'], 24),
                    'start_time': config['search_pruning_start_time'],
                    'verify_on_startup': False,
                    'remove_orphaned': True,
                    'batch_size': 1000,
                    'max_duration_minutes': 120
                },
                'security': {
                    'processing_timeout_seconds': 300,
                    'max_compression_ratio': 100.0,
                    'max_decompressed_size': 10737418240,
                    'max_memory_per_file': 104857600,
                    'enable_panic_recovery': True,
                    'validate_archive_paths': True,
                    'max_text_file_size': 10485760,
                    'restart_workers_on_panic': True
                },
                'reindex': {
                    'enabled': False,
                    'schedule': 'weekly',
                    'interval_hours': 168,
                    'start_time': '02:00',
                    'max_duration_minutes': 240,
                    'clean_index': False
                }
            }

            with open('/etc/truesearch/config.json', 'w') as f:
                json.dump(search_config, f, indent=2)

    @private
    async def check_configuration(self):
        """Check if WebShare service can start with current configuration."""
        config = await self.config()
        errors = []

        # Check if required pools are configured
        if not config['bulk_download_pool']:
            errors.append('Bulk download pool must be configured')
        if not config['search_index_pool'] and config['search_enabled']:
            errors.append('Search index pool must be configured when search is enabled')

        # Check if datasets exist and are mounted
        if config['bulk_download_pool']:
            dataset = f"{config['bulk_download_pool']}/.webshare-private/bulk_download"
            try:
                props = await self.middleware.call('zfs.dataset.get_instance', dataset)
                if props['properties']['mountpoint']['value'] == 'none':
                    errors.append(f'Dataset {dataset} is not mounted')
            except CallError:
                errors.append(f'Dataset {dataset} does not exist')

        if config['search_index_pool'] and config['search_enabled']:
            dataset = f"{config['search_index_pool']}/.webshare-private/search-index"
            try:
                props = await self.middleware.call('zfs.dataset.get_instance', dataset)
                if props['properties']['mountpoint']['value'] == 'none':
                    errors.append(f'Dataset {dataset} is not mounted')
            except CallError:
                errors.append(f'Dataset {dataset} does not exist')

        if errors:
            raise CallError('\n'.join(errors))

    @private
    async def before_start(self):
        """Called before starting the service."""
        await self.check_configuration()
        await self._generate_config_files()
