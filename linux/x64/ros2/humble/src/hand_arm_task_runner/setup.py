from setuptools import find_packages, setup

package_name = "hand_arm_task_runner"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/hook", ["hook/ament_prefix_path.dsv"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="agiuser",
    maintainer_email="agiuser@localhost",
    description="Teach, playback, and sequence execution for OmniHand and Franka arm.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "record_node = hand_arm_task_runner.record_node:main",
            "playback_node = hand_arm_task_runner.playback_node:main",
            "sequence_node = hand_arm_task_runner.sequence_node:main",
            "gui_app = hand_arm_task_runner.gui_app:main",
        ],
    },
)
