# Copyright 2019 TerraPower, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Tests for the uniform mesh geometry converter
"""
import unittest
import random

import numpy

from armi.reactor.tests import test_reactors
from armi.reactor.tests import test_assemblies
from armi.tests import TEST_ROOT
from armi.reactor.converters import uniformMesh
from armi.reactor.flags import Flags


class TestUniformMeshComponents(unittest.TestCase):
    """
    Tests individual operations of the uniform mesh converter

    Only loads reactor once per suite.
    """

    @classmethod
    def setUpClass(cls):
        random.seed(987324987234)  # so it's always the same
        cls.o, cls.r = test_reactors.loadTestReactor(TEST_ROOT)
        # make the mesh a little non-uniform
        a = cls.r.core[4]
        a[2].setHeight(a[2].getHeight() * 1.05)

    def setUp(self):
        self.converter = uniformMesh.UniformMeshGeometryConverter()
        self.converter._sourceReactor = self.r

    def test_computeAverageAxialMesh(self):
        """
        :req:`REQ5cabd0da-b92d-4bc1-b653-8c2139697582`
        """
        refMesh = self.r.core.findAllAxialMeshPoints(
            [self.r.core.getFirstAssembly(Flags.FUEL)]
        )[
            1:
        ]  # pop 0
        self.converter._computeAverageAxialMesh()
        avgMesh = self.converter._uniformMesh

        self.assertEqual(len(refMesh), len(avgMesh))
        self.assertEqual(refMesh[0], avgMesh[0])
        self.assertNotEqual(refMesh[4], avgMesh[4])  # above the fuel.


def applyNonUniformHeightDistribution(reactor):
    """
    Modifies some assemblies to have non-uniform axial meshes

    """
    for a in reactor.core:
        delta = 0.0
        for b in a[:-1]:
            origHeight = b.getHeight()
            newHeight = origHeight * (1 + 0.03 * random.uniform(-1, 1))
            b.setHeight(newHeight)
            delta += newHeight - origHeight
        a[-1].setHeight(a[-1].getHeight() - delta)
        a.calculateZCoords()


class TestUniformMesh(unittest.TestCase):
    """
    Tests full uniform mesh converter

    Loads reactor once per test
    """

    def setUp(self):
        self.o, self.r = test_reactors.loadTestReactor(TEST_ROOT)
        self.converter = uniformMesh.UniformMeshGeometryConverter()

    def test_convertNumberDensities(self):
        refMass = self.r.core.getMass("U235")
        applyNonUniformHeightDistribution(
            self.r
        )  # this changes the mass of everything in the core
        perturbedCoreMass = self.r.core.getMass("U235")
        self.assertNotEqual(refMass, perturbedCoreMass)
        uniformReactor = self.converter.convert(self.r)
        uniformMass = uniformReactor.core.getMass("U235")

        self.assertAlmostEqual(
            perturbedCoreMass, uniformMass
        )  # conversion conserved mass
        self.assertAlmostEqual(
            self.r.core.getMass("U235"), perturbedCoreMass
        )  # conversion didn't change source reactor mass

    def test_applyStateToOriginal(self):
        applyNonUniformHeightDistribution(self.r)  # note: this perturbs the ref. mass
        self.converter.convert(self.r)
        for b in self.converter.convReactor.core.getBlocks():
            b.p.mgFlux = range(33)
            b.p.adjMgFlux = range(33)
            b.p.flux = 5
            b.p.power = 5.0
            b.p.pdens = 0.5

        # check integral and density params
        assemblyPowers = [
            a.calcTotalParam("power") for a in self.converter.convReactor.core
        ]
        totalPower = self.converter.convReactor.core.calcTotalParam(
            "power", generationNum=2
        )
        totalPower2 = self.converter.convReactor.core.calcTotalParam(
            "pdens", volumeIntegrated=True, generationNum=2
        )

        self.converter.applyStateToOriginal()

        for b in self.r.core.getBlocks():
            self.assertAlmostEqual(b.p.flux, 5.0)

        for expectedPower, a in zip(assemblyPowers, self.r.core):
            self.assertAlmostEqual(a.calcTotalParam("power"), expectedPower)

        self.assertAlmostEqual(
            self.r.core.calcTotalParam("pdens", volumeIntegrated=True, generationNum=2),
            totalPower2,
        )
        self.assertAlmostEqual(
            self.r.core.calcTotalParam("power", generationNum=2), totalPower
        )


class TestParamConversion(unittest.TestCase):
    def setUp(self):
        """
        Build two assemblies.

        The source assembly has two blocks, heights 3 and 7 cm. The destination
        has one big block that's 10 cm. Flux is set to 5 and 10 respectively on
        the two source blocks. They are populated with arbitrary flux and pdens
        values.
        """
        self.sourceAssem, self.destinationAssem = test_assemblies.buildTestAssemblies()[
            2:
        ]
        self.height1 = 3.0
        self.height2 = 7.0
        self.sourceAssem[0].setHeight(self.height1)
        self.sourceAssem[0].p.flux = 5.0
        self.sourceAssem[1].setHeight(self.height2)
        self.sourceAssem[1].p.flux = 10.0
        self.sourceAssem.calculateZCoords()
        self.destinationAssem[0].setHeight(self.height1 + self.height2)
        self.destinationAssem.calculateZCoords()

        self.converter = uniformMesh.UniformMeshGeometryConverter()

    def test_setStateFromOverlaps(self):
        """
        Test that state is translated correctly from source to dest assems.

        Here we set flux and pdens to 3 on the source blocks.
        """
        paramList = ["flux", "pdens"]
        for pName in paramList:
            for b in self.sourceAssem:
                b.p[pName] = 3

        def setter(block, vals, _paramNames):
            for pName, val in zip(paramList, vals):
                block.p[pName] = val

        def getter(block, _paramNames):
            return numpy.array([block.p[pName] for pName in paramList])

        # pylint: disable=protected-access
        uniformMesh._setStateFromOverlaps(
            self.sourceAssem, self.destinationAssem, setter, getter, paramList
        )

        sourceFlux1 = self.sourceAssem[0].p.flux
        sourceFlux2 = self.sourceAssem[1].p.flux
        self.assertAlmostEqual(
            self.destinationAssem[0].p.flux,
            (sourceFlux1 * self.height1 + sourceFlux2 * self.height2)
            / (self.height1 + self.height2),
        )


if __name__ == "__main__":
    # import sys;sys.argv = ['', 'TestUniformMesh.test_applyStateToOriginal']
    unittest.main()
