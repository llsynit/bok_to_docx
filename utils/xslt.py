# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import traceback
import logging

from config import JING_JAR, SAXON_JAR, XSLT_FOLDER

from utils.filesystem import Filesystem

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


class Xslt():
    """Class used to run XSLTs"""

    # treat as class variables
    xslt_dir = XSLT_FOLDER
    saxon_jar = SAXON_JAR
    jing_jar = JING_JAR

    @staticmethod
    def init_environment():

        logger.info("Initializing XSLT environment")
        Xslt.saxon_jar = SAXON_JAR
        Xslt.jing_jar = JING_JAR

    def __init__(self,
                 pipeline=None,
                 stylesheet=None,
                 source=None,
                 target=None,
                 parameters={},
                 template=None,
                 stdout_level="INFO",
                 stderr_level="INFO",
                 report=None,
                 cwd=None):
        # assert pipeline or report
        assert stylesheet
        assert source or template

        if not report:
            report = logger

        if not cwd:
            cwd = self.xslt_dir

        self.success = False

        Xslt.init_environment()
        # logger.info(f"Xslt.init_environment() called---", Xslt.saxon_jar)
        try:
            command = ["java", "-jar", str(Xslt.saxon_jar)]
            if source:
                command.append("-s:" + source)
            else:
                command.append("-it:" + template)
            command.append("-xsl:" + stylesheet)
            if target:
                command.append("-o:" + target)
            for param in parameters:
                command.append(param + "=" + parameters[param])

            logger.info("Running XSLT")
            process = Filesystem.run_static(
                command, cwd, logger, stdout_level=stdout_level, stderr_level=stderr_level)
            self.success = process.returncode == 0

        except subprocess.TimeoutExpired:
            logger.error(
                "XSLTen {} tok for lang tid og ble derfor stoppet.".format(stylesheet))

        except Exception:
            logger.error(traceback.format_exc())
            logger.error(
                "An error occured while running the XSLT (" + str(stylesheet) + ")")
