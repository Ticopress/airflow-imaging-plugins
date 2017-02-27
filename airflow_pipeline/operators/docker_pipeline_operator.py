
"""
.. module:: operators.docker_pipeline_operator
    :synopsis: A DockerOperator that registers provenance information in the pipeline

.. moduleauthor:: Ludovic Claude <ludovic.claude@chuv.ch>
"""

try:
    from airflow.operators import DockerOperator
except ImportError:
    from airflow.operators.docker_operator import DockerOperator
from airflow.utils import apply_defaults
from airflow_pipeline.pipelines import TransferPipelineXComs
from mri_meta_extract.files_recording import create_provenance, visit

import logging
import os

from shutil import rmtree


def default_output_folder(folder):
    return folder


class DockerPipelineOperator(DockerOperator, TransferPipelineXComs):
    """
    A DockerOperator that registers provenance information in the pipeline.

    A temporary directory is created on the host and mounted into a container to allow storing files
    that together exceed the default disk size of 10GB in a container. The path to the mounted
    directory can be accessed via the environment variable ``AIRFLOW_TMP_DIR``.

    :param image: Docker image from which to create the container.
    :type image: str
    :param api_version: Remote API version.
    :type api_version: str
    :param command: Command to be run in the container.
    :type command: str or list
    :param cpus: Number of CPUs to assign to the container.
        This value gets multiplied with 1024. See
        https://docs.docker.com/engine/reference/run/#cpu-share-constraint
    :type cpus: float
    :param docker_url: URL of the host running the docker daemon.
    :type docker_url: str
    :param environment: Environment variables to set in the container.
    :type environment: dict
    :param force_pull: Pull the docker image on every run.
    :type force_pull: bool
    :param mem_limit: Maximum amount of memory the container can use. Either a float value, which
        represents the limit in bytes, or a string like ``128m`` or ``1g``.
    :type mem_limit: float or str
    :param network_mode: Network mode for the container.
    :type network_mode: str
    :param tls_ca_cert: Path to a PEM-encoded certificate authority to secure the docker connection.
    :type tls_ca_cert: str
    :param tls_client_cert: Path to the PEM-encoded certificate used to authenticate docker client.
    :type tls_client_cert: str
    :param tls_client_key: Path to the PEM-encoded key used to authenticate docker client.
    :type tls_client_key: str
    :param tls_hostname: Hostname to match against the docker server certificate or False to
        disable the check.
    :type tls_hostname: str or bool
    :param tls_ssl_version: Version of SSL to use when communicating with docker daemon.
    :type tls_ssl_version: str
    :param container_tmp_dir: Mount point inside the container to a temporary directory created on the host by
        the operator. The path is also made available via the environment variable
        ``AIRFLOW_TMP_DIR`` inside the container.
    :type container_tmp_dir: str
    :param container_input_dir: Mount point inside the container to the input directory create on the host by
        the operator. The path is also made available via the environment variable
        ``AIRFLOW_INPUT_DIR`` inside the container.
    :type container_input_dir: str
    :param container_output_dir: Mount point inside the container to the output directory create on the host by
        the operator. The path is also made available via the environment variable
        ``AIRFLOW_OUTPUT_DIR`` inside the container.
    :type container_output_dir: str
    :param output_folder_callable: A reference to an object that is callable.
        It should return the location of the output folder on the host containing the results of the computation.
    :type output_folder_callable: python callable
    :param user: Default user inside the docker container.
    :type user: int or str
    :param volumes: List of volumes to mount into the container, e.g.
        ``['/host/path:/container/path', '/host/path2:/container/path2:ro']``.
    :param xcom_push: Does the stdout will be pushed to the next step using XCom.
           The default is True.
    :type xcom_push: bool
    :param xcom_all: Push all the stdout or just the last line. The default is True (all lines).
    :type xcom_all: bool
    :param parent_task: name of the parent task to use to locate XCom parameters
    :type parent_task: str
    :param on_failure_trigger_dag_id: The dag_id to trigger if this stage of the pipeline has failed,
        i.e. when validate_result_callable raises AirflowSkipException.
    :type on_failure_trigger_dag_id: str
    :param boost_provenance_scan: When True, we consider that all the files from same folder share the same meta-data.
        The processing is 2x faster. Enabled by default.
    :type boost_provenance_scan: bool
    :param session_id_by_patient: Rarely, a data set might use study IDs which are unique by patient (not for the whole study).
        E.g.: LREN data. In such a case, you have to enable this flag. This will use PatientID + StudyID as a session ID.
    :type session_id_by_patient: bool
    """
    template_fields = ('incoming_parameters',)
    template_ext = tuple()
    ui_color = '#e9ffdb'  # nyanza

    @apply_defaults
    def __init__(
            self,
            image,
            api_version=None,
            command=None,
            cpus=1.0,
            docker_url='unix://var/run/docker.sock',
            environment=None,
            force_pull=False,
            mem_limit=None,
            network_mode=None,
            tls_ca_cert=None,
            tls_client_cert=None,
            tls_client_key=None,
            tls_hostname=None,
            tls_ssl_version=None,
            container_tmp_dir='/tmp/airflow',
            container_input_dir='/inputs',
            container_output_dir='/outputs',
            user=None,
            volumes=None,
            xcom_push=True,
            xcom_all=True,
            parent_task=None,
            output_folder_callable=default_output_folder,
            on_failure_trigger_dag_id=None,
            boost_provenance_scan=True,
            session_id_by_patient=False,
            *args, **kwargs):

        DockerOperator.__init__(self,
                                image=image,
                                api_version=api_version,
                                command=command,
                                cpus=cpus,
                                docker_url=docker_url,
                                environment=environment,
                                force_pull=force_pull,
                                mem_limit=mem_limit,
                                network_mode=network_mode,
                                tls_ca_cert=tls_ca_cert,
                                tls_client_cert=tls_client_cert,
                                tls_client_key=tls_client_key,
                                tls_hostname=tls_hostname,
                                tls_ssl_version=tls_ssl_version,
                                tmp_dir=container_tmp_dir,
                                user=user,
                                volumes=volumes,
                                xcom_push=xcom_push,
                                xcom_all=xcom_all,
                                *args, **kwargs)
        TransferPipelineXComs.__init__(self, parent_task)
        self.container_input_dir = container_input_dir
        self.container_output_dir = container_output_dir
        self.output_folder_callable = output_folder_callable
        self.on_failure_trigger_dag_id = on_failure_trigger_dag_id
        self.boost_provenance_scan = boost_provenance_scan
        self.session_id_by_patient = session_id_by_patient
        self.provenance_previous_step_id = None

    def pre_execute(self, context):
        self.read_pipeline_xcoms(context, expected=[
                                 'folder', 'session_id', 'participant_id', 'scan_date',
                                 'dataset'])
        self.pipeline_xcoms['task_id'] = self.task_id

    def execute(self, context):

        self.pipeline_xcoms = self.pipeline_xcoms or {}
        host_output_dir = self.output_folder_callable(
            **self.pipeline_xcoms)
        logs = None

        # Ensure that there is no data in the output folder
        try:
            if os.path.exists(host_output_dir):
                os.removedirs(host_output_dir)
        except Exception:
            logging.error("Cannot cleanup output directory %s before executing Docker container %s",
                          host_output_dir, self.image)

        self.environment['AIRFLOW_INPUT_DIR'] = self.container_input_dir
        self.volumes.append('{0}:{1}'.format(host_input_dir, self.container_input_dir))

        self.environment['AIRFLOW_OUTPUT_DIR'] = self.container_output_dir
        self.volumes.append('{0}:{1}'.format(host_input_dir, self.container_output_dir))

        try:
            logs = super(DockerPipelineOperator, self).execute(context)
        except AirflowException:
            logs = self.cli.logs(container=self.container['Id'])
            logging.error("Docker container %s failed", self.image)
            logging.error("-----------")
            logging.error("Output:")
            logging.error(logs)
            logging.error("-----------")
            # Clean output folder before attempting to retry the
            # computation
            rmtree(host_output_dir, ignore_errors=True)
            self.trigger_dag(context, self.on_failure_trigger_dag_id, logs)
            raise

        self.pipeline_xcoms['folder'] = host_output_dir
        self.pipeline_xcoms['output'] = logs
        self.pipeline_xcoms['error'] = ''

        if ':' not in self.image:
            image = self.image
            version = 'latest'
        else:
            image, version = self.image.split(':')

        provenance_id = create_provenance(pipeline_xcoms['dataset'],
                                          fn_called=image,
                                          fn_version=version,
                                          others='{"docker_image"="%s:%s"}' % (image, version))

        provenance_step_id = visit(self.task_id, host_output_dir, provenance_id,
                                   previous_step_id=self.pipeline_xcoms['provenance_previous_step_id'],
                                   boost=self.boost_provenance_scan, session_id_by_patient=self.session_id_by_patient)
        self.pipeline_xcoms['provenance_previous_step_id'] = provenance_step_id

        self.write_pipeline_xcoms(context)

        return logs